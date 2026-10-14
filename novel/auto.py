"""一键全自动写小说编排器。

主入口：run_auto_novel(spec, project_dir, ...) -> Path (导出文件路径)

阶段流程：
  1. PLANNING     - outline / characters / world / volumes / chapter_plans
  2. WRITING      - 逐章生成 + 质量门控 + 重试
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

import time
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


console = Console()


# ---------------------------------------------------------------------------
# 阶段 1：规划
# ---------------------------------------------------------------------------

def _planning_phase(spec: _AutoSpec, project: S.Project, client: LLMClient, state: AutoState) -> None:
    """跑 outline / characters / world / volumes / 批量细化章纲。"""
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
    client: LLMClient,
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
    try:
        progress.update(task_id, description=f"第 {n} 章：generate + detect + polish")
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

    # 跑质量门控
    progress.update(task_id, description=f"第 {n} 章：质量门控")
    gates = run_all_gates(project, n, client, spec)
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

    # 失败重试
    while not passed and retries < spec.quality.max_retries:
        retries += 1
        progress.update(task_id, description=f"第 {n} 章：重试 {retries}/{spec.quality.max_retries}")
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
    client: LLMClient,
    state: AutoState,
) -> None:
    state.phase = Phase.WRITING
    state.chapters_total = spec.target_chapters
    state.save(project.root)
    console.print("[bold cyan]阶段 2/5：逐章生成[/bold cyan]")

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task_id = progress.add_task(
            "准备中", total=spec.target_chapters,
        )
        for n in range(1, spec.target_chapters + 1):
            if state.is_chapter_done(n):
                progress.update(task_id, advance=1, description=f"第 {n} 章：跳过（已完成）")
                continue
            result = _write_one_chapter(spec, project, n, client, state, progress, task_id)
            state.mark_chapter_done(result)
            state.save(project.root)
            progress.update(task_id, advance=1)


# ---------------------------------------------------------------------------
# 阶段 3：批量润色（如果需要）
# ---------------------------------------------------------------------------

def _polishing_phase(
    spec: _AutoSpec,
    project: S.Project,
    client: LLMClient,
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
    client: LLMClient,
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

def run_auto_novel(
    spec: _AutoSpec,
    project_dir: Path,
    cfg: GlobalConfig | None = None,
    state: AutoState | None = None,
) -> Path:
    """一键全自动写小说主入口。

    Args:
        spec: 用户输入规格（标题/题材/风格/字数/章数/质量档）。
        project_dir: 项目目录（应已 init 过）。
        cfg: cfg 全局配置（默认 .env 加载）。
        state: 现有状态（None 表示新跑；非 None 用于续跑）。

    Returns:
        导出文件的绝对路径（book.md）。
    """
    cfg = cfg or GlobalConfig()
    client = LLMClient(cfg)

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
        if state.phase.value in (Phase.PLANNING.value, "draft"):
            _planning_phase(spec, project, client, state)
        if state.phase.value in (
            Phase.PLANNING.value, Phase.WRITING.value, "draft",
        ):
            _writing_phase(spec, project, client, state)
        if state.phase.value in (
            Phase.WRITING.value, Phase.POLISHING.value,
        ):
            _polishing_phase(spec, project, client, state)
        if state.phase.value in (
            Phase.POLISHING.value, Phase.CONSISTENCY.value,
        ):
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