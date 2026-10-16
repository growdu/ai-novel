"""一键全自动写小说编排器。

主入口：run_auto_novel(spec, project_dir, ...) -> Path (导出文件路径)

阶段流程：
  1. PLANNING     - outline / characters / world / volumes / chapter_plans
  2. WRITING      - 逐章生成 + 质量门控 + 重试
                    （spec.parallel > 1 时并发章节生成，v0.13）
  3. POLISHING    - 批量润色未达标章节
  4. CONSISTENCY  - 跨章一致性检查
  5. EXPORTING    - book.md 合并导出
  6. DONE         - 全部成功

恢复机制：
  - 每写完一章 save() 一次 state
  - 续跑时按 state.chapters_done 跳过
  - 失败章节保留最后一次输出（低质量草稿占位）
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from novel import generator as G
from novel import prompts as P
from novel import storage as S
from novel.auto_state import (
    AutoSpec as _AutoSpec,
)
from novel.auto_state import (
    AutoSpec,
    AutoState,
    ChapterResult,
    Phase,
    QualityPreset,
)
from novel.config import GlobalConfig
from novel.llm import LLMClient
from novel.quality_gates import (
    GateResult,
    run_all_gates,
    summarize,
)
from novel.token_tracker import TokenTracker


console = Console()


# ---------------------------------------------------------------------------
# Web 控制信号
# ---------------------------------------------------------------------------

def _check_control_signal(project_root: Path) -> None:
    """检查 .novel/auto_control.json 里的信号：pause/stop/downgrade/run。"""
    try:
        from novel.web import ControlSignal
    except ImportError:
        return
    signal = ControlSignal.read(project_root)
    if signal == ControlSignal.PAUSE:
        console.print("[yellow]⏸ 检测到 PAUSE 信号：等待用户继续（写 run 到 .novel/auto_control.json 恢复）[/yellow]")
        while ControlSignal.read(project_root) == ControlSignal.PAUSE:
            import time as _t
            _t.sleep(2)
        console.print("[green]▶ 已恢复[/green]")
    elif signal == ControlSignal.STOP:
        console.print("[red]■ 检测到 STOP 信号：停止运行[/red]")
        raise KeyboardInterrupt("user requested stop")
    elif signal == ControlSignal.DOWNGRADE:
        console.print("[yellow]⬇ 检测到 DOWNGRADE：降到 draft 档[/yellow]")
        # 通过 global state 引用降级：直接修改 spec.quality（仅影响后续阶段）
        import novel.auto as _mod
        # 简单方式：后续 write 走 max_iters=1
        # 由于 Python 闭包，这里通过一个全局变量传递
        _mod._DOWNGRADE_REQUESTED = True


_DOWNGRADE_REQUESTED = False


# ---------------------------------------------------------------------------
# 配额自动等待（v0.14+）
# ---------------------------------------------------------------------------

def _wait_for_quota(
    err,
    max_wait_seconds: int = 21600,
    chapter_no: int = 0,
) -> bool:
    """撞到 RateLimitError 时调用。等待 reset 时段（或 cap），Ctrl-C 可断。

    返回 True = 已等完、可重试；False = 用户中断或达到 max_wait，必须退出。
    state 落盘由调用方负责（每次循环开头已经 save 过了）。
    """
    import time as _t

    # 计算等待秒数
    wait = 0
    if err.retry_after_seconds and err.retry_after_seconds > 0:
        wait = err.retry_after_seconds + 30  # 缓冲 30s
    elif err.reset_at and err.reset_at > 0:
        wait = max(0, err.reset_at - int(_t.time())) + 30
    if wait <= 0:
        wait = 60  # 兜底

    wait = min(wait, max_wait_seconds)  # cap 到用户上限

    # 友善提示
    if err.reset_at and err.reset_at > 0:
        reset_str = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(err.reset_at))
    else:
        reset_str = "未知（请参考 minimax 控制台）"
    ch = f"第 {chapter_no} 章" if chapter_no else "LLM 调用"
    console.print(
        f"\n[bold yellow]⏳ 撞到 minimax 配额限制[/bold yellow]"
    )
    console.print(f"   位置：{ch}")
    console.print(f"   HTTP：{err.raw_status}")
    if err.retry_after_seconds:
        console.print(f"   服务器建议：等 {err.retry_after_seconds}s 后重试")
    console.print(f"   配额重置估计：{reset_str}")
    console.print(f"   本次等待：{wait // 60} 分钟（cap {max_wait_seconds // 60} 分钟）")
    console.print(f"   [dim]Ctrl-C 安全退出，state 已保存，下次跑自动续。[/dim]\n")

    # 可中断睡眠：每 60s 醒一次打心跳
    start = _t.time()
    slept = 0
    while slept < wait:
        chunk = min(60, wait - slept)
        try:
            # 检查控制信号（如 PAUSE 已在等）
            _check_control_signal(Path.cwd() / "_dummy_for_signal" if False else Path("."))
        except KeyboardInterrupt:
            console.print("[yellow]用户中断 — state 已保存，下次 `novel auto` 自动续。[/yellow]")
            return False
        try:
            time.sleep(chunk)
        except KeyboardInterrupt:
            console.print("[yellow]用户中断 — state 已保存，下次 `novel auto` 自动续。[/yellow]")
            return False
        slept = int(_t.time() - start)

        # 心跳：每 5 分钟打印一次
        if slept % 300 < 60 and slept > 0:
            remain = (wait - slept) // 60
            console.print(f"[dim]  ⏳ 还在等 quota（剩 {remain} 分钟）...[/dim]")

    return True


def _call_with_quota_retry(
    fn,
    *,
    max_wait_seconds: int = 21600,
    chapter_no: int = 0,
    on_rate_limit=None,
):
    """调用 fn()；遇 RateLimitError 按 _wait_for_quota 等 + 重试。

    Args:
        fn: 可调用对象（如 lambda: client.chat(msgs, ...)）
        max_wait_seconds: 单次撞配额最多等多久（0 = 不等，立刻抛）
        chapter_no: 用于日志
        on_rate_limit: 自定义回调（None 用默认打印；返回 False 不重试）
    """
    attempt = 0
    from novel.llm import RateLimitError
    while True:
        try:
            return fn()
        except RateLimitError as e:
            attempt += 1
            if max_wait_seconds == 0 or on_rate_limit is _PASS_THROUGH:
                # 立刻退出，不等
                raise
            if on_rate_limit is None:
                keep_going = _wait_for_quota(e, max_wait_seconds, chapter_no)
            else:
                keep_going = on_rate_limit(e, max_wait_seconds, chapter_no, attempt)
            if not keep_going:
                raise


# 哨兵：on_rate_limit 传这个表示「不等，直接抛」
_PASS_THROUGH = object()


def _quota_kwargs(spec, chapter_no: int):
    """从 spec 取 (max_wait_seconds, on_rate_limit) 给 _call_with_quota_retry。

    行为：
      - wait_on_quota=False  → max_wait=0 + _PASS_THROUGH（不等，立刻抛）
      - wait_on_quota=True   → 用 spec.max_wait_seconds + 默认 wait+log 回调
    """
    _ = chapter_no  # 预留：将来可基于 chapter_no 动态调整策略
    if not getattr(spec, "wait_on_quota", True):
        return 0, _PASS_THROUGH
    return spec.max_wait_seconds, None


# ---------------------------------------------------------------------------
# 阶段 1：规划
# ---------------------------------------------------------------------------

def _planning_phase(spec: _AutoSpec, project: S.Project, client, state: AutoState) -> None:
    """跑 outline / characters / world / volumes / 批量细化章纲。

    client 参数可以是 LLMClient 或 TokenTracker（后者会累加 token 到 state）。
    """
    state.phase = Phase.PLANNING
    state.save(project.root)
    console.print("[bold cyan]阶段 1/5：规划[/bold cyan]")

    # 1.1 outline
    if not project.outline_path.exists() or project.outline_path.stat().st_size < 200:
        console.print("  生成大纲...")
        msgs = P.build_outline_messages(
            spec.title, spec.theme, spec.genre, spec.target_words,
            project.characters_path.read_text(encoding="utf-8") if project.characters_path.exists() else "",
            "",
        )
        res = client.chat(msgs, temperature=0.85)
        project.outline_path.write_text("# 大纲\n\n" + res.content + "\n", encoding="utf-8")
        state.planning_files.append(str(project.outline_path.relative_to(project.root)))

    # 1.2 characters
    if not project.characters_path.exists() or project.characters_path.stat().st_size < 200:
        console.print("  生成人物志...")
        outline = project.outline_path.read_text(encoding="utf-8")
        msgs = P.build_character_messages(outline, "", "")
        res = client.chat(msgs, temperature=0.85)
        project.characters_path.write_text("# 人物志\n\n" + res.content + "\n", encoding="utf-8")
        state.planning_files.append(str(project.characters_path.relative_to(project.root)))

    # 1.3 world（仅多题材）
    if (spec.genre not in ("现实", "现实 / 严肃文学", "")
            and (not project.world_path.exists() or project.world_path.stat().st_size < 200)):
        console.print("  生成世界观...")
        try:
            G.generate_world(project, spec.theme, spec.genre, client=client)
            state.planning_files.append(str(project.world_path.relative_to(project.root)))
        except Exception as e:
            console.print(f"  [yellow]世界观生成失败（继续）：{e}")

    # 1.4 volumes（章数 > 20 才分卷）
    if spec.target_chapters > 20 and (
        not project.volumes_path.exists() or project.volumes_path.stat().st_size < 200
    ):
        console.print("  生成分卷...")
        try:
            G.generate_volumes(project, client=client)
            state.planning_files.append(str(project.volumes_path.relative_to(project.root)))
        except Exception as e:
            console.print(f"  [yellow]分卷失败（继续）：{e}")

    # 1.5 批量细化所有章纲（用批量生成）
    if spec.target_chapters > 0:
        plans_dir = project.novel_dir / "chapter_plans"
        plans_dir.mkdir(exist_ok=True)
        missing = []
        for n in range(1, spec.target_chapters + 1):
            p = plans_dir / ("%04d.md" % n)
            if not p.exists() or p.stat().st_size < 50:
                missing.append(n)
        if missing:
            console.print(f"  细化 {len(missing)} 章大纲...")
            for n in missing:
                try:
                    G.generate_chapter_plan(project, n, client=client)
                except Exception as e:
                    console.print(f"    [yellow]第 {n} 章 plan 失败（继续）：{e}")
            state.planning_files.append("chapter_plans/")

    state.save(project.root)


# ---------------------------------------------------------------------------
# 阶段 2：逐章生成 + 质量门控
# ---------------------------------------------------------------------------

def _build_chapter_ctx(project: S.Project, n: int) -> dict:
    """构造 ChapterContext dict 喂给 generator。"""
    outline_text = project.outline_path.read_text(encoding="utf-8") if project.outline_path.exists() else ""
    characters_text = project.characters_path.read_text(encoding="utf-8") if project.characters_path.exists() else ""
    style = project.style_path.read_text(encoding="utf-8") if project.style_path.exists() else ""
    genre = project.meta.get("genre", "")
    plan = G.parse_chapter_plan(outline_text, n)
    prev = S.load_chapter(project, n - 1)
    prev_tail = prev[-500:] if prev else ""
    style_samples = G.load_style_samples(project) if hasattr(G, "load_style_samples") else ""
    return {
        "title": project.title,
        "outline": outline_text,
        "characters": characters_text,
        "style": style,
        "genre": genre,
        "chapter_plan": plan,
        "prev_chapter_tail": prev_tail,
        "state": project.state_path.read_text(encoding="utf-8") if project.state_path.exists() else "",
        "foreshadow": project.foreshadowing_path.read_text(encoding="utf-8") if project.foreshadowing_path.exists() else "",
        "world": project.world_path.read_text(encoding="utf-8") if project.world_path.exists() else "",
        "timeline": project.timeline_path.read_text(encoding="utf-8") if project.timeline_path.exists() else "",
        "volumes": project.volumes_path.read_text(encoding="utf-8") if project.volumes_path.exists() else "",
        "arc": (project.arcs_dir / "_overview.md").read_text(encoding="utf-8") if (project.arcs_dir / "_overview.md").exists() else "",
        "rolling_summary": project.rolling_summary_path.read_text(encoding="utf-8") if project.rolling_summary_path.exists() else "",
        "style_samples": style_samples,
    }


def _write_one_chapter(
    spec: _AutoSpec,
    project: S.Project,
    n: int,
    client,  # LLMClient 或 TokenTracker
    state: AutoState,
    progress: Progress,
    task_id,
) -> ChapterResult:
    """单章：generate → validate → retry → polish → save。失败兜底为草稿。"""
    start = time.time()
    ctx = _build_chapter_ctx(project, n)
    req = G.ChapterRequest(chapter_no=n, target_words=spec.per_chapter_words)
    last_err = ""
    last_result = None
    retries = 0


# 第一次生成（用 extended 让 detect/review/polish 自带循环）
    # 撞到 RateLimitError 时由 _call_with_quota_retry 内部等到 quota 重置再重试；
    # 真 abort 时（Ctrl-C / 超 max_wait / --no-wait）抛给外层 → chapter 标 failed。
    try:
        progress.update(task_id, description=f"第 {n} 章：generate + detect + polish")
        mw, ol = _quota_kwargs(spec, n)
        last_result = _call_with_quota_retry(
            lambda: G.write_chapter_extended(
                req, ctx, project=project, client=client,
                max_iters=spec.quality.iters,
                update_after=True,
                verbose=False,
                do_polish=True,
            ),
            max_wait_seconds=mw,
            chapter_no=n,
            on_rate_limit=ol,
        )
    except Exception as e:
        last_err = str(e)
        console.print(f"  [red]第 {n} 章 generate 异常：{e}[/red]")

    if last_result is None:
        # 兜底：手写一个空内容占位（让后续流程不中断）
        placeholder = "（自动生成失败占位 — 请重跑或用 `novel chapter N` 手动重写）\n"
        try:
            S.save_chapter(project, n, placeholder, backup=False)
        except Exception:
            pass
        return ChapterResult(
            chapter_no=n, status="failed", word_count=0, retries=retries,
            elapsed_ms=int((time.time() - start) * 1000), error=last_err,
        )

    # 保存首版
    S.save_chapter(project, n, last_result.content, backup=True)

    # 跑质量门控（也算 LLM 调用，撞配额时同样自动等）
    progress.update(task_id, description=f"第 {n} 章：质量门控")
    mw, ol = _quota_kwargs(spec, n)
    gates = _call_with_quota_retry(
        lambda: run_all_gates(project, n, client, spec),
        max_wait_seconds=mw,
        chapter_no=n,
        on_rate_limit=ol,
    )
    passed, failed = summarize(gates)
    if passed:
        progress.update(task_id, description=f"第 {n} 章：通过 ✓")
        return ChapterResult(
            chapter_no=n,
            status="generated",
            word_count=last_result.word_count,
            iterations=last_result.iterations,
            retries=retries,
            ai_flavor=_extract_ai_score(gates),
            radar=_extract_radar(gates),
            elapsed_ms=int((time.time() - start) * 1000),
        )

    # 失败重试（每个 LLM 调用都包 quota retry）
    while not passed and retries < spec.quality.max_retries:
        retries += 1
        progress.update(task_id, description=f"第 {n} 章：重试 {retries}/{spec.quality.max_retries}")
        feedback = _build_retry_feedback(failed, ctx)
        try:
            mw, ol = _quota_kwargs(spec, n)
            last_result = _call_with_quota_retry(
                lambda: _regenerate_chapter(spec, project, n, ctx, client, feedback),
                max_wait_seconds=mw,
                chapter_no=n,
                on_rate_limit=ol,
            )
            S.save_chapter(project, n, last_result.content, backup=True)
        except Exception as e:
            last_err = str(e)
            console.print(f"  [yellow]第 {n} 章重试 {retries} 异常：{e}[/yellow]")
            continue

        mw2, ol2 = _quota_kwargs(spec, n)
        gates = _call_with_quota_retry(
            lambda: run_all_gates(project, n, client, spec),
            max_wait_seconds=mw2,
            chapter_no=n,
            on_rate_limit=ol2,
        )
        passed, failed = summarize(gates)
        if passed:
            progress.update(task_id, description=f"第 {n} 章：重试后通过 ✓")
            break

    # 不论是否通过，都保留最后一次输出（草稿占位策略）
    status = "generated" if passed else "failed"
    if not passed:
        console.print(
            f"  [yellow]第 {n} 章未通过所有门控（{len(failed)} 项不达标），保留草稿占位[/yellow]"
        )
    return ChapterResult(
        chapter_no=n,
        status=status,
        word_count=S.chapter_word_count(last_result.content),
        iterations=last_result.iterations,
        retries=retries,
        ai_flavor=_extract_ai_score(gates),
        radar=_extract_radar(gates),
        elapsed_ms=int((time.time() - start) * 1000),
        error=last_err if not passed else "",
    )


def _regenerate_chapter(
    spec: _AutoSpec,
    project: S.Project,
    n: int,
    ctx: dict,
    client: LLMClient,
    feedback: str,
):
    """基于反馈重新生成整章。"""
    req = G.ChapterRequest(chapter_no=n, target_words=spec.per_chapter_words)
    # 用 polish_messages 把反馈作为额外指示
    p_msgs = P.build_polish_messages(
        content=S.load_chapter(project, n) or "",
        chapter_plan=ctx.get("chapter_plan", ""),
        prev_tail=ctx.get("prev_chapter_tail", ""),
        detect_report=feedback,
        extra="",
    )
    res = client.chat_with_continuation(
        p_msgs, target_words=spec.per_chapter_words,
        max_total_tokens=20000, temperature=0.9,
    )
    new_content = (res.content or "").strip()
    return G.ChapterResult(
        chapter_no=n, content=new_content, word_count=S.chapter_word_count(new_content),
        iterations=1, detect_report=feedback, review_report="", history=None,
    )


def _build_retry_feedback(failed: list[GateResult], ctx: dict) -> str:
    """把失败原因拼成 LLM 反馈。"""
    lines = ["【自动质量门控未通过】", "请解决："]
    for g in failed:
        lines.append(f"- {g.name}：{g.detail}")
    lines.append("")
    lines.append("重写时请严格遵循字数、对话占比、心理描写、避免 AI 句式等规则。")
    return "\n".join(lines)


def _extract_ai_score(gates: list[GateResult]) -> int | None:
    for g in gates:
        if g.name == "ai_flavor" and g.score is not None:
            return int(g.score)
    return None


def _extract_radar(gates: list[GateResult]) -> int | None:
    for g in gates:
        if g.name == "radar" and g.score is not None:
            return int(g.score)
    return None


def _writing_phase(
    spec: _AutoSpec,
    project: S.Project,
    client,  # LLMClient 或 TokenTracker
    state: AutoState,
) -> None:
    state.phase = Phase.WRITING
    state.chapters_total = spec.target_chapters
    state.save(project.root)
    console.print("[bold cyan]阶段 2/5：逐章生成[/bold cyan]")

    # 注入 Web 控制信号检查
    _check_control_signal(project.root)

    # spec.parallel >= 2 时走并发（v0.13）
    if spec.parallel >= 2:
        _writing_phase_parallel(spec, project, client, state)
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("{task.fields[tokens_fmt]}", style="cyan"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task_id = progress.add_task(
            "准备中", total=spec.target_chapters, tokens_fmt="token 0 | ¥0.00",
        )
        for n in range(1, spec.target_chapters + 1):
            if state.is_chapter_done(n):
                progress.update(task_id, advance=1, description=f"第 {n} 章：跳过（已完成）")
                continue
            # 写每章前检查暂停 / 停止 / 降级
            _check_control_signal(project.root)
            result = _write_one_chapter(spec, project, n, client, state, progress, task_id)
            # 累加 token 到 state
            if hasattr(client, "prompt_tokens"):
                state.cumulative_tokens += result.total_tokens or 0
                state.cumulative_prompt_tokens += result.prompt_tokens
                state.cumulative_completion_tokens += result.completion_tokens
                # 估算成本
                from novel.budget import estimate_cost_cny
                state.cumulative_cost_cny += estimate_cost_cny(
                    result.prompt_tokens, result.completion_tokens,
                    getattr(client, "model", ""),
                )
                result.estimated_cost_cny = estimate_cost_cny(
                    result.prompt_tokens, result.completion_tokens,
                    getattr(client, "model", ""),
                )
                # 更新进度条上的 token/cost 显示
                progress.update(
                    task_id,
                    tokens_fmt=(
                        f"token {state.cumulative_tokens:,} | "
                        f"¥{state.cumulative_cost_cny:.3f}"
                    ),
                )
            state.mark_chapter_done(result)
            state.save(project.root)
            progress.update(task_id, advance=1)


def _writing_phase_parallel(
    spec: _AutoSpec,
    project: S.Project,
    client,
    state: AutoState,
) -> None:
    """并发版 _writing_phase（v0.13）。

    用 ThreadPoolExecutor 并发执行章节生成：每章 LLM 调用是 I/O-bound，
    适合多线程。注意 4 个并发问题：
      1. state.json 写竞争 → state_lock 串行化
      2. progress.update 竞争 → progress_lock 串行化
      3. 跨 worker 章节顺序（prev_tail）→ prev_cache 用 in-memory cache
      4. _check_control_signal 单文件读取 → 由 OS 文件读写原子性保证

    性能预期：spec.parallel=3 实测节省 ~50-65% 时间（v0.12.1 实测 6 章对比）。
    """
    max_workers = max(1, spec.parallel)

    state_lock = threading.Lock()
    progress_lock = threading.Lock()
    prev_cache_lock = threading.Lock()
    prev_cache: dict[int, str] = {}  # chapter_no -> 当前已生成的正文

    def safe_progress(**kwargs):
        with progress_lock:
            progress.update(task_id, **kwargs)

    def worker(n: int) -> None:
        """单个 worker：检查 → 构建 ctx（含 prev_cache）→ 写 → state.save。"""
        # 0. 跳过已完成
        with state_lock:
            if state.is_chapter_done(n):
                safe_progress(advance=1, description=f"第 {n} 章：跳过（已完成）")
                return

        # 1. 控制信号（每个 worker 进入前都检查；文件读取是原子的）
        try:
            _check_control_signal(project.root)
        except SystemExit:
            return  # 被信号终止，安静退出

        # 2. 构造 ctx（含 cache 覆盖 prev_tail）
        ctx = _build_chapter_ctx(project, n)
        with prev_cache_lock:
            prev_content = prev_cache.get(n - 1)
        if prev_content is not None:
            # 截取末尾 500 字做下一章 context（与 _build_chapter_ctx 默认一致）
            ctx["prev_chapter_tail"] = prev_content[-500:]

        # 3. 写本章（在 safe_progress 包装下，更新到 progress bar）
        result = _write_one_chapter_locked(spec, project, n, client, state, safe_progress)

        # 4. 累加 token + 标完成 + save（state_lock 串行化）
        with state_lock:
            if hasattr(client, "prompt_tokens"):
                state.cumulative_tokens += result.total_tokens or 0
                state.cumulative_prompt_tokens += result.prompt_tokens
                state.cumulative_completion_tokens += result.completion_tokens
                from novel.budget import estimate_cost_cny
                state.cumulative_cost_cny += estimate_cost_cny(
                    result.prompt_tokens, result.completion_tokens,
                    getattr(client, "model", ""),
                )
            state.mark_chapter_done(result)
            state.save(project.root)
            with prev_cache_lock:
                prev_cache[n] = result.content or ""

        # 5. 进度 +1
        with progress_lock:
            progress.update(
                task_id,
                advance=1,
                tokens_fmt=(
                    f"token {state.cumulative_tokens:,} | "
                    f"¥{state.cumulative_cost_cny:.3f}"
                ),
            )

    console.print(f"[dim]并发模式：{max_workers} workers[/dim]")

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("{task.fields[tokens_fmt]}", style="cyan"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task_id = progress.add_task(
            "准备中", total=spec.target_chapters, tokens_fmt="token 0 | ¥0.00",
        )
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(worker, n) for n in range(1, spec.target_chapters + 1)]
            # 收集结果；任一 worker 抛异常则打印但不中断其他
            for f in as_completed(futures):
                exc = f.exception()
                if exc is not None:
                    console.print(f"[red]并发 worker 异常：{exc}[/red]")


def _write_one_chapter_locked(
    spec: _AutoSpec,
    project: S.Project,
    n: int,
    client,
    state: AutoState,
    safe_progress,  # callable(**kwargs) -> None，做了 progress 加锁
):
    """_write_one_chapter 的并发安全变体：把内部 progress.update 调用
    通过 safe_progress 串行化（避免 Rich Progress 多线程崩溃）。

    行为与 _write_one_chapter 一致；只把 progress 替换为加锁包装。
    """
    start = time.time()
    ctx = _build_chapter_ctx(project, n)  # 重建一次；上一层可能再覆盖一次
    req = G.ChapterRequest(chapter_no=n, target_words=spec.per_chapter_words)

    last_err = ""
    last_result = None
    retries = 0

    # 第一次生成
    try:
        safe_progress(description=f"第 {n} 章：generate + detect + polish")
        last_result = G.write_chapter_extended(
            req, ctx, project=project, client=client,
            max_iters=spec.quality.iters,
            update_after=True,
            verbose=False,
            do_polish=True,
        )
    except Exception as e:
        last_err = str(e)
        console.print(f"  [red]第 {n} 章 generate 异常：{e}[/red]")

    if last_result is None:
        placeholder = "（自动生成失败占位 — 请重跑或用 `novel chapter N` 手动重写）\n"
        try:
            S.save_chapter(project, n, placeholder, backup=False)
        except Exception:
            pass
        return ChapterResult(
            chapter_no=n, status="failed", word_count=0, retries=retries,
            elapsed_ms=int((time.time() - start) * 1000), error=last_err,
        )

    # 保存首版
    S.save_chapter(project, n, last_result.content, backup=True)

    # 跑质量门控
    safe_progress(description=f"第 {n} 章：质量门控")
    gates = run_all_gates(project, n, client, spec)
    passed, failed = summarize(gates)
    if passed:
        safe_progress(description=f"第 {n} 章：通过 ✓")
        return ChapterResult(
            chapter_no=n,
            status="generated",
            word_count=last_result.word_count,
            iterations=last_result.iterations,
            retries=retries,
            ai_flavor=_extract_ai_score(gates),
            radar=_extract_radar(gates),
            elapsed_ms=int((time.time() - start) * 1000),
        )

    # 失败重试
    while not passed and retries < spec.quality.max_retries:
        retries += 1
        safe_progress(description=f"第 {n} 章：重试 {retries}/{spec.quality.max_retries}")
        feedback = _build_retry_feedback(failed, ctx)
        try:
            last_result = _regenerate_chapter(
                spec, project, n, ctx, client, feedback,
            )
            S.save_chapter(project, n, last_result.content, backup=True)
        except Exception as e:
            last_err = str(e)
            console.print(f"  [yellow]第 {n} 章重试 {retries} 异常：{e}[/yellow]")
            continue

        gates = run_all_gates(project, n, client, spec)
        passed, failed = summarize(gates)
        if passed:
            safe_progress(description=f"第 {n} 章：重试后通过 ✓")
            break

    status = "generated" if passed else "failed"
    if not passed:
        console.print(
            f"  [yellow]第 {n} 章未通过所有门控（{len(failed)} 项不达标），保留草稿占位[/yellow]"
        )
        return ChapterResult(
            chapter_no=n,
            status=status,
            word_count=last_result.word_count if last_result else 0,
            iterations=last_result.iterations if last_result else 0,
            retries=retries,
            elapsed_ms=int((time.time() - start) * 1000),
            error=last_err if not passed else "",
        )

    return ChapterResult(
        chapter_no=n, status=status, word_count=last_result.word_count,
        iterations=last_result.iterations, retries=retries,
        elapsed_ms=int((time.time() - start) * 1000),
    )


# ---------------------------------------------------------------------------
# 阶段 3：批量润色（如果需要）
# ---------------------------------------------------------------------------

def _polishing_phase(
    spec: _AutoSpec,
    project: S.Project,
    client,  # LLMClient 或 TokenTracker
    state: AutoState,
) -> None:
    """如果精修档以下 / 状态跳过了这一步。"""
    state.phase = Phase.POLISHING
    state.save(project.root)
    if spec.quality.value == "draft":
        state.polished = True
        state.save(project.root)
        return
    console.print("[bold cyan]阶段 3/5：批量润色[/bold cyan]")

    # 对未通过的章节，强制 polish 一次
    failed = state.chapters_failed
    if not failed:
        state.polished = True
        state.save(project.root)
        return
    for n in failed:
        try:
            outline_text = project.outline_path.read_text(encoding="utf-8") if project.outline_path.exists() else ""
            plan = G.parse_chapter_plan(outline_text, n)
            prev = S.load_chapter(project, n - 1)
            prev_tail = prev[-500:] if prev else ""
            content = S.load_chapter(project, n) or ""
            msgs = P.build_polish_messages(content, plan, prev_tail, "", "")
            res = client.chat_with_continuation(
                msgs, target_words=spec.per_chapter_words,
                max_total_tokens=20000, temperature=0.9,
            )
            new_text = (res.content or "").strip()
            if new_text:
                S.save_chapter(project, n, new_text, backup=True)
                console.print(f"  [green]第 {n} 章批量润色完成[/green]")
        except Exception as e:
            console.print(f"  [yellow]第 {n} 章批量润色失败：{e}[/yellow]")

    state.polished = True
    state.save(project.root)


# ---------------------------------------------------------------------------
# 阶段 4：跨章一致性
# ---------------------------------------------------------------------------

def _consistency_phase(
    spec: _AutoSpec,
    project: S.Project,
    client,  # LLMClient 或 TokenTracker
    state: AutoState,
) -> None:
    state.phase = Phase.CONSISTENCY
    state.save(project.root)
    console.print("[bold cyan]阶段 4/5：跨章一致性[/bold cyan]")
    try:
        G.check_consistency(project, client=client, lookback=20)
        console.print("  [green]一致性报告已保存到 consistency_report.md[/green]")
    except Exception as e:
        console.print(f"  [yellow]一致性检查失败：{e}[/yellow]")
    state.consistency_checked = True
    state.save(project.root)


# ---------------------------------------------------------------------------
# 阶段 5：导出
# ---------------------------------------------------------------------------

def _exporting_phase(
    spec: _AutoSpec,
    project: S.Project,
    state: AutoState,
) -> Path:
    state.phase = Phase.EXPORTING
    state.save(project.root)
    console.print("[bold cyan]阶段 5/5：导出[/bold cyan]")
    out = G.export_combined(project, fmt="md")
    if out is None:
        # 兜底路径
        out = project.root / "book.md"
        chapters = project.list_chapters()
        if chapters:
            titles = S.load_titles(project)
            with open(out, "w", encoding="utf-8") as f:
                f.write("# " + project.title + "\n\n")
                for c in chapters:
                    n = int(c.stem)
                    t = titles.get("%04d" % n, "")
                    f.write("## 第 " + str(n) + " 章 " + (t or "") + "\n\n")
                    f.write(c.read_text(encoding="utf-8").strip())
                    f.write("\n\n---\n\n")
    state.exported_path = str(out.relative_to(project.root))
    state.phase = Phase.DONE
    state.save(project.root)
    return out


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def spec_from_project(
    project_dir: Path,
    quality: QualityPreset = QualityPreset.PREMIUM,
    target_chapters: int = 0,
) -> _AutoSpec:
    """从已 init 的项目目录（.novel/project.yaml）恢复 AutoSpec。

    用法：当用户已经跑过 init（+ 模板）但还想跑 auto 时，
    调用此函数复用项目元数据，避免再次手动输入 title/genre/style。

    Args:
        project_dir: 项目目录（必须有 .novel/project.yaml）。
        quality: 质量档（默认 PREMIUM；一般 CLI 层会从 --quality 覆盖）。
        target_chapters: 显式章数（0 = 由 __post_init__ 按 target_words/3000 自动算）。

    Returns:
        AutoSpec：从 project.yaml 字段填充的规格。

    Raises:
        FileNotFoundError: .novel/ 目录不存在（项目没 init）。
    """
    proj = S.load_project(project_dir)
    meta = proj.meta or {}
    target_words = int(meta.get("target_words") or 100000)
    return _AutoSpec(
        title=proj.title,
        theme=meta.get("theme", ""),
        genre=meta.get("genre", "现实 / 严肃文学"),
        style=meta.get("style_preset", ""),
        target_words=target_words,
        target_chapters=target_chapters,
        quality=quality,
    )


def run_auto_novel(
    spec: _AutoSpec,
    project_dir: Path,
    cfg: GlobalConfig | None = None,
    state: AutoState | None = None,
    budget_cny: float = 0.0,
    plans_only: bool = False,
    skip_plans: bool = False,
) -> Path:
    """一键全自动写小说主入口。

    Args:
        spec: 用户输入规格（标题/题材/风格/字数/章数/质量档）。
        project_dir: 项目目录（应已 init 过）。
        cfg: cfg 全局配置（默认 .env 加载）。
        state: 现有状态（None 表示新跑；非 None 用于续跑）。
        budget_cny: 预算上限（CNY）。0 = 不限制。
        plans_only: 只跑规划阶段（生成 outline + 所有章纲），生成完后停。
        skip_plans: 跳过规划阶段，直接进入写作（用现有 outline/chapter_plans）。

    Returns:
        导出文件的绝对路径（book.md）。
    """
    cfg = cfg or GlobalConfig()
    raw_client = LLMClient(cfg)
    # 包一层 TokenTracker，记录所有 LLM 调用的 token 用量
    client = TokenTracker(raw_client, model=cfg.model)

    # 加载项目
    if not (project_dir / ".novel").exists():
        from novel.storage import init_project
        init_project(project_dir, spec.title, theme=spec.theme, meta={
            "genre": spec.genre,
            "target_words": spec.target_words,
            "style_preset": spec.style,
        })
    project = S.Project(
        root=project_dir.resolve(),
        title=spec.title,
        meta=S.load_project(project_dir).meta,
    )

    # 加载或新建状态
    if state is None:
        state = AutoState.load(project_dir) or AutoState(
            spec=spec.__dict__,
            chapters_total=spec.target_chapters,
        )
        state.spec = {
            "title": spec.title,
            "theme": spec.theme,
            "genre": spec.genre,
            "style": spec.style,
            "target_words": spec.target_words,
            "target_chapters": spec.target_chapters,
            "quality": spec.quality.value,
        }
    state.save(project_dir)

    console.print(
        f"[bold green]novel auto:[/bold green] {spec.title} | "
        f"{spec.target_chapters} 章 × {spec.per_chapter_words} 字 | {spec.quality.value} 档"
    )
    console.print(f"  项目目录: {project_dir}")
    if state.progress_ratio > 0:
        console.print(
            f"  续跑模式: 已完成 {len(state.chapters_done)}/{state.chapters_total} 章"
        )

    try:
        if state.phase.value in (Phase.PLANNING.value, "draft") and not skip_plans:
            _planning_phase(spec, project, client, state)
        if state.phase.value in (
            Phase.PLANNING.value, Phase.WRITING.value, "draft",
        ):
            _writing_phase(spec, project, client, state)
        if state.phase.value in (
            Phase.WRITING.value, Phase.POLISHING.value,
        ):
            if not plans_only:
                _polishing_phase(spec, project, client, state)
        if state.phase.value in (
            Phase.POLISHING.value, Phase.CONSISTENCY.value,
        ):
            if not plans_only:
                _consistency_phase(spec, project, client, state)
        if state.phase.value in (
            Phase.CONSISTENCY.value, Phase.EXPORTING.value,
        ):
            out = _exporting_phase(spec, project, state)
    except KeyboardInterrupt:
        console.print("[yellow]用户中断。再次跑 `novel auto --resume` 可续跑。[/yellow]")
        state.last_error = "用户中断（Ctrl-C）"
        state.save(project_dir)
        raise
    except Exception as e:
        console.print(f"[red]致命错误：{e}[/red]")
        state.phase = Phase.FAILED
        state.last_error = str(e)
        state.save(project_dir)
        raise

    if plans_only:
        # 只跑规划，标记阶段为 finished 提示
        state.phase = Phase.POLISHING  # 下一个待运行阶段
        state.save(project_dir)
        console.print("[green]✓ 规划阶段完成（章纲已生成）[/green]")
        console.print(f"  章纲目录: {project_dir / '.novel' / 'chapter_plans'}")
        console.print("  [dim]下一步：review 章纲后，跑 `novel auto ... --skip-plans` 进入写作阶段[/dim]")
        return project_dir / "book.md"  # 不存在也无所谓

    # 汇总
    _print_summary(state, out)
    return out


def _print_summary(state: AutoState, output: Path) -> None:
    """打印最终汇总表。"""
    from rich.table import Table

    elapsed = timedelta(seconds=int(state.updated_at - state.started_at))
    table = Table(title="novel auto 汇总")
    table.add_column("指标")
    table.add_column("值")
    table.add_row("总章节", str(state.chapters_total))
    table.add_row("已完成", str(len(state.chapters_done)))
    table.add_row("未达标", str(len(state.chapters_failed)))
    table.add_row("累计字数", f"{state.total_words:,}")
    table.add_row("累计 token", f"{state.cumulative_tokens:,}")
    if state.cumulative_prompt_tokens:
        table.add_row(
            "  输入/输出 token",
            f"{state.cumulative_prompt_tokens:,} / {state.cumulative_completion_tokens:,}",
        )
    if state.cumulative_cost_cny > 0:
        cost_str = f"¥{state.cumulative_cost_cny:.3f}"
        if state.budget_cny > 0:
            ratio = (state.cumulative_cost_cny / state.budget_cny) * 100
            cost_str += f" (预算 ¥{state.budget_cny:.2f} 的 {ratio:.0f}%)"
        table.add_row("估算成本", cost_str)
    table.add_row("用时", str(elapsed))
    table.add_row("输出", str(output))
    console.print(table)
    if state.chapters_failed:
        console.print(
            f"\n[yellow]提示：{len(state.chapters_failed)} 章未通过所有门控，"
            f"已保留草稿占位。可用 `novel polish N` 或 `novel chat N '...'` 手动重写。[/yellow]"
        )
    else:
        console.print(f"\n[green]✓ 全部 {state.chapters_total} 章通过门控。[/green]")