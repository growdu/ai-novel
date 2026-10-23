"""v0.15+ novel daemon：后台长跑，循环「跑 6 阶段 → 评估 criteria → 反馈注入 → 再跑」。

不是 v0.14 的 `auto` 一次跑完；是真正的「运维级」长循环。

核心循环（`_daemon_loop`）：

    while not should_stop():
        iter_count += 1
        if iter_count > max_iterations:  stop
        if cost_so_far > cost_budget:      stop
        if time_so_far > max_time:        stop

        # 1. 跑 6 阶段（如果上轮 feedback，把 feedback 注入到 spec.extra）
        run_auto_novel(spec, project_dir)   # 复用 v0.14 全套逻辑（含配额等待）

        # 2. 评估硬指标
        criteria = load_criteria(criteria_path)
        if not criteria:
            log("无 criteria 文件 → 全 pass，退出")
            break
        full_text = read_all_chapters(project_dir)
        prev = format_feedback_for_next_iter(prev_report) if prev_report else ""
        report = evaluate_via_llm(criteria, full_text, prev)

        # 3. 记录到 state
        state.iteration_count = iter_count
        state.last_criteria_report = report.raw_text
        state.last_iter_passed = report.all_passed
        state.save()

        if report.all_passed:
            log("✅ 全 pass → 退出")
            break

        # 4. 注入反馈给下一轮；循环
        next_iter_spec.extra = format_feedback_for_next_iter(report)

终止条件（OR，任一满足即退）:
  - all_passed True
  - iteration_count >= max_iterations
  - cumulative_cost >= cost_budget
  - elapsed_time >= max_time
  - 看到 .novel/stop_daemon 文件（用户从 web 点 stop）
  - 进程收到 SIGINT / SIGTERM（Ctrl-C）

环境与依赖：
  - 复用 run_auto_novel（novel/auto.py）
  - 复用 _call_with_quota_retry → 撞 minimax 配额自动等
  - 复用 novel serve → Web 仪表盘显示 daemon 状态
"""
from __future__ import annotations

import json
import re
import signal
import time
from dataclasses import replace
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from novel import storage as S
from novel.auto_state import AutoSpec, AutoState, Phase
from novel.criteria import (
    DEFAULT_BATCH_OVERLAP,
    DEFAULT_BATCH_SIZE,
    EvaluatorReport,
    evaluate_batches,
    format_feedback_for_next_iter,
    load_criteria,
)
from novel.llm import LLMClient


console = Console()


# ---------------------------------------------------------------------------
# Stop signal
# ---------------------------------------------------------------------------

STOP_FILE_NAME = "stop_daemon"


def _stop_signal_path(project_dir: Path) -> Path:
    return project_dir / ".novel" / STOP_FILE_NAME


def is_stop_requested(project_dir: Path) -> bool:
    """用户从 web UI 或外部脚本写 .novel/stop_daemon 即可停止。"""
    p = _stop_signal_path(project_dir)
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass
        return True
    return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _read_all_chapters(project_dir: Path) -> str:
    """拼所有章节为单字符串（旧版整书评估路径，保留兼容）。"""
    proj = S.load_project(project_dir)
    parts: list[str] = []
    for c in proj.list_chapters():
        n = c.stem
        text = c.read_text(encoding="utf-8") if c.exists() else ""
        parts.append(f"## 第 {n} 章\n\n{text}")
    return "\n\n---\n\n".join(parts)


def _read_chapter_list(project_dir: Path) -> list[dict]:
    """读全书章节成 [{no, title, words, text}, ...]，按章号升序。

    v0.17 分块评估用。字数在 Python 侧精确统计好塞进 prompt——让 LLM 自己
    数字数在长篇场景必错，而 criteria.md 里字数类指标占比很高。
    """
    proj = S.load_project(project_dir)
    out: list[dict] = []
    for path in proj.list_chapters():
        try:
            no = int(path.stem)
        except ValueError:
            continue
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        title = ""
        for line in text.splitlines():
            s = line.strip().lstrip("#").strip()
            if s and not s.startswith("第"):
                title = s[:40]
                break
            if s.startswith("第"):
                # 「第 12 章 标题」→ 只取标题部分
                m = re.search(r"第\s*\d+\s*章\s*(.*)", s)
                if m and m.group(1).strip():
                    title = m.group(1).strip()[:40]
                break
        out.append({
            "no": no,
            "title": title,
            "words": S.chapter_word_count(text),
            "text": text,
        })
    out.sort(key=lambda c: c["no"])
    return out


def _check_should_stop(
    project_dir: Path,
    iter_count: int,
    max_iterations: int,
    cost_so_far: float,
    cost_budget: float,
    started_at: float,
    max_time_seconds: int,
) -> tuple[bool, str]:
    """OR 多重停止条件；返回 (should_stop, reason)。"""
    if is_stop_requested(project_dir):
        return True, "用户写入 .novel/stop_daemon"
    if iter_count >= max_iterations:
        return True, f"达到 max_iterations={max_iterations}"
    if cost_budget > 0 and cost_so_far >= cost_budget:
        return True, f"cost_budget={cost_budget:.2f} 用完（实际 {cost_so_far:.2f}）"
    if max_time_seconds > 0 and (time.time() - started_at) >= max_time_seconds:
        return True, f"max_time_seconds={max_time_seconds} 到期"
    return False, ""


def _install_signal_handlers() -> None:
    """Ctrl-C 触发 SIGINT；systemd stop 触发 SIGTERM。两个都优雅退出。"""
    def _graceful_exit(signum, frame):
        console.print(f"\n[yellow]收到信号 {signum}，daemon 准备退出（下一轮 check 时退出）[/yellow]")
        # 不直接 raise；让主循环下一轮迭代 check 时退出
        # 用全局 flag 简单实现
        _daemon_loop._stop_signal_received = True

    _daemon_loop._stop_signal_received = False  # type: ignore[attr-defined]
    signal.signal(signal.SIGINT, _graceful_exit)
    signal.signal(signal.SIGTERM, _graceful_exit)


def _signal_stop_requested() -> bool:
    return getattr(_daemon_loop, "_stop_signal_received", False)


def _daemon_loop(
    spec: AutoSpec,
    project_dir: Path,
    cfg,
    max_iterations: int = 3,
    cost_budget: float = 0.0,
    max_time_seconds: int = 0,
    eval_batch_size: int = DEFAULT_BATCH_SIZE,
    eval_overlap: int = DEFAULT_BATCH_OVERLAP,
) -> AutoState:
    """主循环。返回最终的 AutoState（已 DONE 或已停在某轮）。"""
    from novel.auto import run_auto_novel

    started_at = time.time()
    _install_signal_handlers()

    # 读上轮 state（如果之前 daemon 跑过）
    state = AutoState.load(project_dir)
    if state is None:
        state = AutoState(spec=spec.__dict__)
    state.save(project_dir)

    # 加载 criteria
    criteria_lines = load_criteria(spec.daemon_criteria_path) if spec.daemon_criteria_path else []
    if not criteria_lines:
        console.print("[yellow]⚠️ 未提供 criteria 文件（spec.daemon_criteria_path 空）；daemon 跑 1 轮后退出[/yellow]")
    console.print(f"[bold cyan]daemon 启动[/bold cyan]  criteria 条数：{len(criteria_lines)}  max_iterations={max_iterations}  cost_budget={cost_budget}  max_time={max_time_seconds}s")

    last_report: Optional[EvaluatorReport] = None

    while True:
        iter_no = state.iteration_count + 1
        # 注入上轮反馈
        current_spec = spec
        if last_report is not None and not last_report.all_passed:
            feedback = format_feedback_for_next_iter(last_report)
            current_spec = replace(spec, extra=feedback)

        # v0.16+ surgical：第 1 轮跑全本，之后只重写未通过章
        only_chapters: list[int] | None = None
        if last_report is not None and not last_report.all_passed and last_report.failed_chapters:
            # 取上轮 failed + 之前 passed（确保 surgical 范围精确）
            all_chs = set(range(1, spec.target_chapters + 1))
            already_passed = set(state.passed_chapters)
            to_rewrite = set(last_report.failed_chapters) - already_passed
            if to_rewrite:
                only_chapters = sorted(to_rewrite)
                console.print(
                    f"[cyan]surgical 重写：第 {only_chapters} 章"
                    f"（其余 {len(all_chs) - len(to_rewrite)} 章已通过，保留）[/cyan]"
                )

        console.print(f"\n[bold]═══ 第 {iter_no} 轮迭代 ═══[/bold]")
        try:
            out = run_auto_novel(
                current_spec, project_dir, cfg=cfg,
                budget_cny=cost_budget or spec.budget_cny,
                only_chapters=only_chapters,
            )
        except Exception as e:
            console.print(f"[red]本轮 run_auto_novel 失败：{e}[/red]")
            state.last_error = str(e)
            state.save(project_dir)
            return state

        # 累计 cost 由 run_auto_novel 写到 state.cumulative_cost_cny
        state = AutoState.load(project_dir) or state
        state.iteration_count = iter_no
        state.save(project_dir)
        console.print(f"[green]本轮完成[/green]  book.md={out.name if out else 'N/A'}  cost={state.cumulative_cost_cny:.3f}  elapsed={int(time.time()-started_at)}s")

        # 检查停止条件（在评估前先判）
        should, reason = _check_should_stop(
            project_dir, iter_no, max_iterations,
            state.cumulative_cost_cny, cost_budget,
            started_at, max_time_seconds,
        )
        if should:
            console.print(f"[yellow]⏹ daemon 退出：{reason}[/yellow]")
            state.last_iter_passed = False
            state.save(project_dir)
            return state
        if _signal_stop_requested():
            console.print("[yellow]⏹ daemon 退出：用户 Ctrl-C / SIGTERM[/yellow]")
            state.last_iter_passed = False
            state.save(project_dir)
            return state

        # 评估 criteria
        if not criteria_lines:
            # 没 criteria → 这一轮就是最终轮
            console.print("[green]无 criteria → daemon 完成[/green]")
            state.last_iter_passed = True
            state.save(project_dir)
            return state

        console.print(
            f"[cyan]评估硬指标（分块 LLM 调用，batch={eval_batch_size} "
            f"overlap={eval_overlap}）...[/cyan]"
        )
        chapters = _read_chapter_list(project_dir)
        prev_feedback = format_feedback_for_next_iter(last_report) if last_report else ""

        def _on_progress(bi: int, total: int, rep, error: str = "") -> None:
            head = f"  [dim]批 {bi + 1}/{total}[/dim]"
            if error:
                console.print(f"{head} [yellow]调用失败，跳过：{error[:60]}[/yellow]")
                return
            if rep is not None and rep.failed_chapters:
                ns = rep.failed_chapters
                span = f"{ns[0]}-{ns[-1]} 章" if len(ns) > 6 else ",".join(str(n) for n in ns)
                console.print(f"{head} [yellow]{len(ns)} 章未达标：{span}[/yellow]")
            else:
                console.print(f"{head} [green]全通过[/green]")
        eval_client = LLMClient(cfg)
        try:
            report = evaluate_batches(
                criteria_lines, chapters,
                batch_size=eval_batch_size,
                overlap=eval_overlap,
                prev_feedback=prev_feedback,
                client=eval_client,
                on_progress=_on_progress,
            )
        except Exception as e:
            console.print(f"[red]criteria 评估失败：{e}[/red]")
            state.last_criteria_report = f"ERROR: {e}"
            state.last_iter_passed = False
            state.save(project_dir)
            return state
        finally:
            # 评估的 token 只活在这个临时 client 上（53 批可跑 1.5 小时）。
            # 不回写的话 --cost-budget 完全看不见这笔开销。
            from novel.auto import _flush_cost

            _flush_cost(state, eval_client)
            state.save(project_dir)

        state.last_criteria_report = report.raw_text
        state.last_iter_passed = report.all_passed
        state.last_failed_chapters = list(report.failed_chapters)
        # v0.16+ surgical：累加 passed_chapters（一次跑过的章不再重写）
        if report.all_passed:
            state.passed_chapters = sorted(
                set(state.passed_chapters) | set(range(1, spec.target_chapters + 1))
            )
        else:
            # 本轮通过 = all - failed；与历史 passed 取并集
            all_chs = set(range(1, spec.target_chapters + 1))
            iter_passed = all_chs - set(report.failed_chapters)
            state.passed_chapters = sorted(set(state.passed_chapters) | iter_passed)
        state.save(project_dir)

        # 打印评估结果
        if report.all_passed:
            console.print(f"[green]✅ 全部 {len(report.criteria)} 条 criteria 通过[/green]")
            console.print(f"   {report.summary}")
            return state
        else:
            failed = [c for c in report.criteria if not c.passed]
            console.print(f"[yellow]❌ {len(failed)}/{len(report.criteria)} 条 criteria 未通过[/yellow]")
            for c in failed[:5]:
                console.print(f"   - [{c.id}] {c.text}")
                console.print(f"     证据：{c.evidence[:80]}")
                console.print(f"     建议：{c.suggestion[:80]}")
            if report.top_priority_fixes:
                console.print(f"   [bold]优先修复[/bold]：")
                for fix in report.top_priority_fixes[:3]:
                    console.print(f"     * {fix}")

        # 检查停止条件（在评估后）
        should, reason = _check_should_stop(
            project_dir, iter_no, max_iterations,
            state.cumulative_cost_cny, cost_budget,
            started_at, max_time_seconds,
        )
        if should:
            console.print(f"[yellow]⏹ daemon 退出：{reason}[/yellow]")
            state.save(project_dir)
            return state
        if _signal_stop_requested():
            console.print("[yellow]⏹ daemon 退出：用户 Ctrl-C / SIGTERM[/yellow]")
            state.save(project_dir)
            return state

        # 继续下一轮
        last_report = report
        console.print(f"[dim]继续下一轮...[/dim]")


# ---------------------------------------------------------------------------
# systemd unit 生成
# ---------------------------------------------------------------------------

SYSTEMD_UNIT_TEMPLATE = """[Unit]
Description=novel-writer daemon: {project_dir}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
WorkingDirectory={cwd}
ExecStart={python} {cli_py} daemon run {project_arg} {extra_args}
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""


def render_systemd_unit(
    project_dir: Path,
    python: str = "/usr/bin/python3",
    cli_py: str = "/home/ubuntu/ai-novel/novel_cli.py",
    user: str = "root",
    extra_args: str = "--serve --max-iterations 5 --cost-budget 30",
) -> str:
    """生成 systemd unit file（输出 stdout；用户 > file）。"""
    project_arg = str(project_dir.resolve())
    return SYSTEMD_UNIT_TEMPLATE.format(
        project_dir=project_arg,
        project_arg=project_arg,
        python=python,
        cli_py=cli_py,
        user=user,
        cwd=str(project_dir.resolve()),
        extra_args=extra_args,
    )


# ---------------------------------------------------------------------------
# 状态查询（novel daemon status）
# ---------------------------------------------------------------------------

def format_status_table(state: AutoState | None, spec: AutoSpec | None) -> str:
    """渲染 daemon 状态文本（status 子命令 + web UI 用）。"""
    if state is None:
        return "（daemon 未运行过）"
    elapsed = int(state.updated_at - state.started_at) if state.started_at else 0
    h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
    table = Table(title=f"novel daemon · iteration={state.iteration_count}")
    table.add_column("指标", style="cyan")
    table.add_column("值")
    table.add_row("阶段", state.phase.value)
    table.add_row("已完成", f"{len(state.chapters_done)}/{state.chapters_total}")
    table.add_row("累计字数", f"{state.total_words:,}")
    table.add_row("累计 token", f"{state.cumulative_tokens:,}")
    table.add_row("累计成本", f"¥{state.cumulative_cost_cny:.3f}")
    if spec and spec.budget_cny > 0:
        table.add_row("成本预算", f"¥{spec.budget_cny:.2f}")
    if spec and spec.max_iterations > 0:
        table.add_row("最大迭代", f"{spec.max_iterations}")
    table.add_row("用时", f"{h}:{m:02d}:{s:02d}")
    table.add_row("本轮全 pass", "✅" if state.last_iter_passed else "❌")
    if state.last_criteria_report:
        snippet = state.last_criteria_report[:120].replace("\n", " ")
        table.add_row("评估摘要", snippet)
    from rich.console import Console as _C
    buf = _C(record=True, width=80)
    buf.print(table)
    return buf.export_text()
