"""配置与设置命令：setup / config / version / prompt。

属于「环境配置」，对应 DEVELOPER_GUIDE §4 的 配置层。
注意：v0.13.x 模块化后，装饰用裸函数（不直接 `@app.command()`），
调用由 register(app) 完成。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from novel import __version__
from novel.config import load_global


console = Console()


def _print_cfg(cfg) -> None:
    t = Table(title="当前配置")
    t.add_column("项")
    t.add_column("值")
    for k, v in cfg.masked().items():
        t.add_row(k, str(v))
    console.print(t)


def config(
    show: bool = typer.Option(False, "--show"),
    set_base_url: str = typer.Option(None, "--base-url"),
    set_model: str = typer.Option(None, "--model"),
    set_key: str = typer.Option(None, "--api-key"),
    dry_run: bool = typer.Option(None, "--dry-run/--no-dry-run"),
):
    """查看 / 修改全局配置（API key / base_url / model / DRY_RUN）。"""
    cfg = load_global()
    if set_base_url:
        os.environ["OPENAI_BASE_URL"] = set_base_url
        cfg.base_url = set_base_url
    if set_model:
        os.environ["OPENAI_MODEL"] = set_model
        cfg.model = set_model
    if set_key:
        os.environ["OPENAI_API_KEY"] = set_key
        cfg.api_key = set_key
    if dry_run is not None:
        os.environ["DRY_RUN"] = "true" if dry_run else "false"
        cfg.dry_run = dry_run
    _print_cfg(cfg)


def version(
    short: bool = typer.Option(False, "--short", "-s", help="只输出版本号，无颜色"),
):
    """显示 novel-writer 版本号与运行环境。"""
    py = sys.version.split()[0]
    if short:
        typer.echo(__version__)
        raise typer.Exit()
    table = Table(title="novel-writer 环境信息", show_header=False)
    table.add_column("项", style="cyan")
    table.add_column("值")
    table.add_row("novel-writer", __version__)
    table.add_row("Python", py)
    table.add_row("平台", sys.platform)
    table.add_row("typer", typer.__version__ if hasattr(typer, "__version__") else "unknown")
    table.add_row("模型", load_global().model)
    table.add_row("base_url", load_global().base_url)
    console.print(table)


def setup(
    force: bool = typer.Option(False, "--force", "-f", help="已存在 .env 时仍覆盖"),
    non_interactive: bool = typer.Option(False, "--no-input", help="用环境变量 / 已有 .env，非交互"),
):
    """首次配置向导：交互式生成 .env。

    依次询问 API base URL、API key、模型、温度、章节字数、DRY_RUN。
    已存在 .env 时默认跳过；--force 覆盖。
    """
    env_path = Path.cwd() / ".env"
    if env_path.exists() and not force:
        console.print(f"[yellow].env 已存在：[/yellow] {env_path}\n[dim]用 --force 覆盖，或直接编辑。[/dim]")
        if non_interactive:
            return
        if not Confirm.ask("是否覆盖现有 .env？", default=False):
            return
    if non_interactive:
        cfg = load_global()
        lines = [
            f"OPENAI_BASE_URL={cfg.base_url}",
            f"OPENAI_API_KEY={cfg.api_key or ''}",
            f"OPENAI_MODEL={cfg.model}",
            f"TEMPERATURE={cfg.temperature}",
            f"TOP_P={cfg.top_p}",
            f"MAX_TOKENS={cfg.max_tokens}",
            f"TARGET_CHAPTER_WORDS={cfg.target_chapter_words}",
            f"DRY_RUN={'true' if cfg.dry_run else 'false'}",
        ]
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        console.print(f"[green]已写入：[/green] {env_path}")
        return
    console.print(Panel.fit(
        "[bold]novel-writer 首次配置向导[/bold]\n\n"
        "下面会询问：API 地址、API key、模型、温度、DRY_RUN。\n"
        "所有问题都可以直接回车用默认值。\n"
        "完成后会在当前目录生成 .env 文件。",
        title="setup",
    ))
    base_url = Prompt.ask("API base URL", default="https://api.minimaxi.com/v1")
    api_key = Prompt.ask("API key", password=True, default=load_global().api_key or "")
    model = Prompt.ask("模型", default="minimax-Text-01")
    temperature = float(Prompt.ask("temperature（0.7 稳 / 0.95 放飞）", default="0.9"))
    chapter_words = int(Prompt.ask("目标章节字数", default="3000"))
    dry_run = Confirm.ask("开启 DRY_RUN 模式（不真调用 API）？", default=False)
    lines = [
        "# novel-writer 配置（由 setup 命令生成，可手动修改）",
        f"OPENAI_BASE_URL={base_url}",
        f"OPENAI_API_KEY={api_key}",
        f"OPENAI_MODEL={model}",
        f"TEMPERATURE={temperature}",
        "TOP_P=0.95",
        "MAX_TOKENS=4096",
        f"TARGET_CHAPTER_WORDS={chapter_words}",
        f"DRY_RUN={'true' if dry_run else 'false'}",
        "",
    ]
    env_path.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"\n[green]✓ 已写入：[/green] {env_path}")
    console.print("\n[dim]下一步：[/dim]")
    console.print("  1. novel doctor      # 验证配置")
    console.print("  2. novel init my_novel --title '你的小说标题' --genre 悬疑 --style 冷峻")
    console.print("  3. cd my_novel && novel outline && novel characters && novel chapter 1")


def prompt(
    name: str = typer.Argument(..., help="提示词名"),
    show: bool = typer.Option(False, "--show", "-s", help="打印内容"),
    edit: bool = typer.Option(False, "--edit", "-e", help="用 $EDITOR 编辑"),
    lines: int = typer.Option(20, "--lines", "-l", help="show 模式下打印多少行"),
    reset: bool = typer.Option(False, "--reset", help="恢复默认（删除项目副本）"),
):
    """查看/编辑当前提示词。每个项目的提示词独立存放在 .novel/prompts/。"""
    from novel import prompts as P
    from novel import storage as S
    proj = S.load_project()
    proj_prompts_dir = proj.novel_dir / "prompts"
    proj_prompts_dir.mkdir(parents=True, exist_ok=True)
    proj_copy = proj_prompts_dir / (name + ".md")
    default_path = P.PROMPTS_DIR / (name + ".md")
    if not default_path.exists():
        console.print("[red]提示词 %s.md 不存在。可用提示词：[/red]" % name)
        for f in sorted(P.PROMPTS_DIR.glob("*.md")):
            console.print("  - " + f.stem)
        raise typer.Exit(1)
    if reset:
        if proj_copy.exists():
            proj_copy.unlink()
        console.print("[green]已恢复默认（删除项目副本 %s）[/green]" % proj_copy)
        return
    if not proj_copy.exists():
        proj_copy.write_text(default_path.read_text(encoding="utf-8"), encoding="utf-8")
        console.print("[dim]已从默认复制到 %s[/dim]" % proj_copy)
    if show:
        text = proj_copy.read_text(encoding="utf-8")
        all_lines = text.splitlines()
        for i, line in enumerate(all_lines[:lines], 1):
            console.print("%4d  %s" % (i, line))
        if len(all_lines) > lines:
            console.print("...（共 %d 行）" % len(all_lines))
        return
    if edit:
        editor = os.environ.get("EDITOR", "vi")
        console.print("用 $EDITOR=%s 编辑 %s" % (editor, proj_copy))
        subprocess.call([editor, str(proj_copy)])
        console.print("[green]已保存。[/green]")
        return
    console.print("[bold]项目副本[/bold] %s (%d 字节)" % (proj_copy, proj_copy.stat().st_size))
    console.print("[bold]默认路径[/bold] %s" % default_path)
    console.print("使用 --show 查看内容，--edit 编辑，--reset 恢复默认。")


def register(app: typer.Typer) -> None:
    """注册配置类命令到给定 typer.Typer 实例。"""
    app.command()(config)
    app.command()(version)
    app.command()(setup)
    app.command()(prompt)
