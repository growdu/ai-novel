"""v0.15+ novel daemon 命令族：run / status / stop / unit。

`novel daemon run` 启动后台长跑循环（前台显示日志；--serve 同时启 Web 仪表盘）。
`novel daemon status` 看当前 state。
`novel daemon stop` 在 `.novel/stop_daemon` 写一个空文件，daemon 下一轮 check 时退出。
`novel daemon unit` 输出 systemd unit file（用户 > file）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from novel import storage as S
from novel.auto_state import AutoSpec, AutoState, QualityPreset
from novel.config import load_global
from novel.daemon import (
    _daemon_loop,
    _stop_signal_path,
    is_stop_requested,
    render_systemd_unit,
)


console = Console()


def _load_or_init_spec(project_dir: Path, project_name: str) -> AutoSpec:
    """从 .novel/project.yaml + state 重建 spec（确保 daemon 用一致参数）。"""
    proj = S.load_project(project_dir)
    meta = proj.meta or {}
    quality_str = (meta.get("quality") or "standard").upper()
    try:
        quality = QualityPreset(quality_str)
    except ValueError:
        quality = QualityPreset.STANDARD
    return AutoSpec(
        title=meta.get("title", project_name),
        theme=meta.get("theme", ""),
        genre=meta.get("genre", "现实 / 严肃文学"),
        style=meta.get("style_preset", ""),
        target_words=int(meta.get("target_words", 30000) or 30000),
        target_chapters=int(meta.get("target_chapters", 0) or 0),
        quality=quality,
        budget_cny=float(meta.get("budget_cny", 0) or 0),
    )


def run(
    name: str = typer.Argument(None, help="项目目录名（默认 cwd）"),
    criteria: str = typer.Option("", "--criteria", "-c", help="用户硬指标文件路径（quality_criteria.md）"),
    max_iterations: int = typer.Option(3, "--max-iterations", help="最多迭代轮数"),
    cost_budget: float = typer.Option(0.0, "--cost-budget", help="总成本上限 CNY；0=不限"),
    max_time: int = typer.Option(0, "--max-time", help="总时间上限秒；0=无限"),
    eval_batch_size: int = typer.Option(
        12, "--eval-batch-size",
        help="分块评估时每批章数（v0.17；长篇必用，避免整书塞进单 prompt）",
    ),
    eval_overlap: int = typer.Option(
        4, "--eval-overlap", help="分块评估的批间重叠章数（给「每 N 章」窗口指标留衔接）",
    ),
    parallel: int = typer.Option(
        1, "--parallel", "-p", help="写作阶段并发 worker 数；1=串行，>=2 并发（长篇强烈建议 3+）",
    ),
    serve: bool = typer.Option(False, "--serve", help="同时启 Web 仪表盘"),
    serve_port: int = typer.Option(8765, "--serve-port"),
    here: bool = typer.Option(False, "--here", help="就地对当前目录运行"),
    force: bool = typer.Option(False, "--force", help="重置 state.iteration_count 重新开始"),
):
    """novel daemon：后台长跑循环，跑 6 阶段 → 评估 criteria → 不达标就再跑。

    终止条件：全 pass / max_iterations / cost_budget / max_time / 用户写 .novel/stop_daemon / Ctrl-C。

    Examples:
        # 标准用法：3 章 + 硬指标
        novel daemon run my_novel --criteria ./quality_criteria.md

        # 长跑大项目：开 Web 仪表盘
        novel daemon run my_novel --criteria ./criteria.md --max-iterations 5 \\
            --cost-budget 50 --serve
    """
    project_dir = Path.cwd() if here or not name else (Path.cwd() / name)
    if not (project_dir / ".novel").exists():
        console.print(f"[red]{project_dir} 不是 novel 项目（缺 .novel/）[/red]")
        raise typer.Exit(1)

    if force:
        state = AutoState.load(project_dir)
        if state:
            state.iteration_count = 0
            state.last_criteria_report = ""
            state.last_iter_passed = False
            state.save(project_dir)
            console.print("[cyan]已重置 iteration_count=0[/cyan]")

    # 解析 spec
    spec = _load_or_init_spec(project_dir, name or project_dir.name)
    spec.daemon_criteria_path = criteria
    spec.max_iterations = max_iterations
    spec.max_time_seconds = max_time
    spec.budget_cny = cost_budget or spec.budget_cny
    spec.parallel = max(1, parallel)

    # 启动 web 仪表盘
    if serve:
        try:
            from novel.web import start_serve_in_thread
            start_serve_in_thread(project_dir, port=serve_port)
            console.print(f"[dim]Web 仪表盘已启动：http://127.0.0.1:{serve_port}[/dim]")
        except Exception as e:
            console.print(f"[yellow]Web 仪表盘启动失败：{e}[/yellow]")

    console.print(Panel.fit(
        f"[bold green]novel daemon 启动[/bold green]\n"
        f"项目: {project_dir}\n"
        f"criteria: {criteria or '[无 → 跑 1 轮后退出]'}\n"
        f"目标: {spec.target_chapters} 章 × {spec.target_words} 字\n"
        f"max_iterations={max_iterations}  cost_budget={cost_budget}  max_time={max_time}s\n"
        f"评估分块: batch={eval_batch_size} overlap={eval_overlap}   写作并发: {spec.parallel}",
        title="novel daemon run",
    ))

    cfg = load_global()
    final_state = _daemon_loop(
        spec, project_dir, cfg,
        max_iterations=max_iterations,
        cost_budget=cost_budget,
        max_time_seconds=max_time,
        eval_batch_size=eval_batch_size,
        eval_overlap=eval_overlap,
    )

    # 输出总结
    if final_state.last_iter_passed:
        console.print(f"\n[bold green]✅ daemon 完成[/bold green]  iteration={final_state.iteration_count}  cost=¥{final_state.cumulative_cost_cny:.3f}")
    else:
        console.print(f"\n[yellow]⚠️ daemon 退出（未全 pass）[/yellow]  iteration={final_state.iteration_count}  cost=¥{final_state.cumulative_cost_cny:.3f}")


def status(
    name: str = typer.Argument(None, help="项目目录名"),
    here: bool = typer.Option(False, "--here"),
):
    """看 daemon 当前 state（iteration / cost / last criteria report）。"""
    project_dir = Path.cwd() if here or not name else (Path.cwd() / name)
    if not (project_dir / ".novel").exists():
        console.print(f"[red]{project_dir} 不是 novel 项目[/red]")
        raise typer.Exit(1)

    state = AutoState.load(project_dir)
    spec = _load_or_init_spec(project_dir, name or project_dir.name)

    from novel.daemon import format_status_table
    table_text = format_status_table(state, spec)
    console.print(table_text)

    # 顺便提示 stop file
    if is_stop_requested(project_dir):
        console.print("[green]检测到 .novel/stop_daemon（已生效，daemon 会在下轮 check 时退出）[/green]")


def stop(
    name: str = typer.Argument(None, help="项目目录名"),
    here: bool = typer.Option(False, "--here"),
):
    """向 .novel/stop_daemon 写空文件，daemon 下一轮 check 时退出。"""
    project_dir = Path.cwd() if here or not name else (Path.cwd() / name)
    if not (project_dir / ".novel").exists():
        console.print(f"[red]{project_dir} 不是 novel 项目[/red]")
        raise typer.Exit(1)
    p = _stop_signal_path(project_dir)
    p.touch()
    console.print(f"[green]已写入 {p}[/green]")
    console.print("[dim]daemon 下一轮 check 时检测到该文件，退出循环。Ctrl-C 立刻退出。[/dim]")


def unit(
    project: str = typer.Option(".", "--project", help="要守护的项目目录"),
    user: str = typer.Option("root", "--user", help="systemd unit 的 User 字段"),
    python: str = typer.Option(sys.executable, "--python", help="systemd unit 用的 Python 解释器"),
    cli: str = typer.Option(str(Path(__file__).resolve().parent.parent.parent / "novel_cli.py"), "--cli", help="novel_cli.py 路径"),
    extra_args: str = typer.Option("--serve --max-iterations 5 --cost-budget 30", "--extra-args", help="传给 daemon run 的额外参数"),
):
    """输出 systemd unit file（> file 保存到 /etc/systemd/system/）。"""
    project_dir = Path(project).resolve()
    if not (project_dir / ".novel").exists():
        console.print(f"[yellow]警告：{project_dir} 不是 novel 项目（缺 .novel/）；生成的 unit 仍可用，请先 init。[/yellow]")
    content = render_systemd_unit(
        project_dir=project_dir,
        python=python,
        cli_py=cli,
        user=user,
        extra_args=f"--here --criteria {project_dir}/quality_criteria.md {extra_args}",
    )
    # typer.echo 走 stdout 不会加 ANSI 颜色（unit file 是纯文本）
    typer.echo(content, color=False)
    console.print()
    console.print("[dim]用法（root 权限）：[/dim]")
    console.print(f"  sudo tee /etc/systemd/system/novel-{project_dir.name}.service <<< '<上面输出>'")
    console.print(f"  sudo systemctl daemon-reload")
    console.print(f"  sudo systemctl enable --now novel-{project_dir.name}.service")
    console.print(f"  journalctl -u novel-{project_dir.name}.service -f  # 跟日志")
    console.print(f"  systemctl stop novel-{project_dir.name}  # 或 novel daemon stop")


def register(app: typer.Typer) -> None:
    """注册 novel daemon 命令组（4 子命令）。"""
    # typer 没原生子命令组 API；用 add_typer 嵌套
    import typer as _typer
    sub = _typer.Typer(help="novel daemon：后台长跑循环（v0.15+）", no_args_is_help=True)
    sub.command(name="run")(run)
    sub.command(name="status")(status)
    sub.command(name="stop")(stop)
    sub.command(name="unit")(unit)
    app.add_typer(sub, name="daemon")
