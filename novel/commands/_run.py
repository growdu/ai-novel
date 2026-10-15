"""运行编排入口：auto / serve。

auto 是 6 阶段流水线（v0.11+）；serve 是 Web 仪表盘。
"""
from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from novel.config import load_global
from novel import storage as S


console = Console()


def auto(
    name: str = typer.Argument(None, help="项目目录名（与 --here 互斥）"),
    title: str = typer.Option(..., "--title", "-t", help="小说标题（必填）"),
    theme: str = typer.Option("", "--theme", help="一句话主题"),
    genre: str = typer.Option("现实 / 严肃文学", "--genre", "-g", help="题材"),
    style: str = typer.Option("", "--style", "-s", help="文风（预设名或自由描述）"),
    words: int = typer.Option(30000, "--words", "-w", help="目标总字数"),
    chapters: int = typer.Option(None, "--chapters", help="显式指定章节数"),
    quality: str = typer.Option("standard", "--quality", help="质量档：draft / standard / premium"),
    budget: float = typer.Option(0.0, "--budget", help="成本上限 CNY；0=不限"),
    resume: bool = typer.Option(False, "--resume", help="强制续跑"),
    fresh: bool = typer.Option(False, "--fresh", help="强制从头跑（覆盖旧进度）"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    here: bool = False,
    force: bool = False,
    serve: bool = typer.Option(False, "--serve", help="同时启动 Web 仪表盘"),
    serve_port: int = typer.Option(8765, "--serve-port", help="仪表盘端口"),
    plans_only: bool = typer.Option(False, "--plans-only", help="只跑规划阶段"),
    skip_plans: bool = typer.Option(False, "--skip-plans", help="跳过规划阶段，直接进入写作"),
    parallel: int = typer.Option(0, "--parallel", "-P", help="并发章节 worker 数；v0.13+"),
):
    """一键全自动写小说：给定最小信息，自动跑完规划→写作→润色→一致性→导出。

    自动可恢复：每章写完即保存到 .novel/auto_state.json，Ctrl-C 后下次
    novel auto 自动从中断处续跑（无需 --resume）。

    --serve 启动 Web 仪表盘：浏览器打开 http://127.0.0.1:8765 看实时进度。

    Examples:
        novel auto demo --title "冬夜的灰" --theme "1995 东北命案" \\
            --genre 悬疑 --style 冷峻 --words 60000 --quality premium
    """
    from novel.auto import run_auto_novel
    from novel.auto_state import AutoSpec, QualityPreset, AutoState

    # 解析 quality
    try:
        quality_preset = QualityPreset(quality)
    except ValueError:
        console.print(f"[red]未知 quality：{quality}。可选：draft/standard/premium[/red]")
        raise typer.Exit(1)

    cfg = load_global()
    is_dry = dry_run or cfg.dry_run

    # 项目目录
    if here:
        project_dir = Path.cwd()
    elif name:
        project_dir = Path.cwd() / name
    else:
        console.print("[red]请提供 NAME 或加 --here。[/red]")
        raise typer.Exit(1)

    # 项目 init / load
    proj = None
    try:
        proj = S.load_project(project_dir)
        if not here and name and not force:
            pass
    except S.ProjectNotFoundError:
        from rich.prompt import Confirm
        if here and not force:
            if not Confirm.ask(f"在 {project_dir} 创建新项目？", default=True):
                raise typer.Exit()
        project_dir.mkdir(parents=True, exist_ok=True)
        proj = S.init_project(
            project_dir,
            title,
            theme=theme,
            meta={"genre": genre, "target_words": words, "style_preset": style},
        )

    if proj is None:
        console.print("[red]无法初始化或加载项目。[/red]")
        raise typer.Exit(1)

    # 续跑检测（仅打印 + 让 run_auto_novel 自动从 .novel/auto_state.json 加载）
    state_path = proj.root / ".novel" / "auto_state.json"
    if state_path.exists() and not fresh:
        st = AutoState.load(proj.root)
        if st and st.spec.get("title") == title:
            done = sum(1 for r in st.chapter_results.values() if r.status in ("generated", "polished"))
            console.print(Panel.fit(
                f"[green]检测到上次进度[/green]\n"
                f"阶段: {st.phase.value} | 已完成: {done}/{st.chapters_total}\n"
                f"已用 token: {st.cumulative_tokens:,} | 用时: {(st.updated_at - st.started_at)/60:.0f} 分钟\n\n"
                f"[dim]直接 Enter 续跑；输入 n 重新开始[/dim]",
                title="novel auto 续跑",
            ))
            if not resume:
                ans = Prompt.ask("续跑？", default="y")
                if ans.lower().startswith("n"):
                    fresh = True  # 用户拒绝续跑，转 fresh

    # 构造 spec
    spec = AutoSpec(
        title=title,
        theme=theme or "",
        genre=genre,
        style=style,
        target_words=words,
        target_chapters=chapters or 0,
        quality=quality_preset,
        parallel=parallel,
    )

    # 启动 Web 仪表盘
    if serve:
        try:
            from novel.web import serve_background
            bg_server = serve_background(proj.root, port=serve_port, open_browser=True)
            console.print(f"[dim]Web 仪表盘已启动：http://127.0.0.1:{serve_port}[/dim]")
        except OSError as e:
            console.print(f"[yellow]仪表盘启动失败（端口 {serve_port} 占用？）：{e}[/yellow]")

    try:
        # state=None 让 run_auto_novel 自动从 .novel/auto_state.json 加载已存在的进度
        out = run_auto_novel(
            spec, proj.root, cfg=cfg,
            budget_cny=budget,
            plans_only=plans_only,
            skip_plans=skip_plans,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断。再次运行 novel auto 自动续跑。[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(f"[red]novel auto 失败：{e}[/red]")
        raise typer.Exit(1)
    console.print(Panel.fit(f"[green]✓ 全书完成：[/green] {out}", title="novel auto"))


def serve(
    port: int = typer.Option(8765, "--port", "-p", help="监听端口"),
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址（默认仅本机）"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="自动打开浏览器"),
    project: str = typer.Option(".", "--project", help="要监控的项目目录（默认当前目录）"),
):
    """启动 Web 仪表盘：浏览器查看 novel auto 实时进度。

    默认 http://127.0.0.1:8765，每 2 秒刷新一次。
    暂停 / 继续 / 降级 / 停止 按钮会写控制信号到 .novel/auto_control.json。
    """
    import webbrowser as _wb

    project_dir = Path(project).resolve()
    if not (project_dir / ".novel").exists():
        console.print(f"[red]{project_dir} 不是 novel 项目目录（缺少 .novel/）[/red]")
        raise typer.Exit(1)

    from novel.web import make_handler

    handler = make_handler(project_dir)
    server = ThreadingHTTPServer((host, port), handler)

    if open_browser:
        threading.Timer(
            1.0,
            lambda: _wb.open(f"http://{host}:{port}"),
        ).start()

    console.print(Panel.fit(
        f"[green]novel-writer 仪表盘已启动[/green]\n\n"
        f"URL: [bold]http://{host}:{port}[/bold]\n"
        f"项目: {project_dir}\n\n"
        f"[dim]按 Ctrl-C 停止服务器[/dim]",
        title="novel serve",
    ))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("[yellow]停止仪表盘[/yellow]")
        server.shutdown()


def register(app: typer.Typer) -> None:
    """注册 auto / serve 命令。"""
    app.command()(auto)
    app.command()(serve)
