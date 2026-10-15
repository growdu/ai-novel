"""输出命令：export / index。

导出整书稿 + 索引查询。
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from novel import generator as G
from novel import storage as S


console = Console()


def export(
    fmt: str = typer.Option("md", "--format", "-f", help="md 或 txt"),
    output: str = typer.Option(None, "--output", "-o", help="输出路径"),
):
    """合并所有章节为单一文件（书稿）。"""
    proj = S.load_project()
    out = G.export_combined(proj, fmt=fmt, output_path=Path(output) if output else None)
    if out is None:
        console.print("[yellow]没有章节可导出。[/yellow]")
    else:
        size = out.stat().st_size
        console.print("[green]已导出[/green] " + str(out) + " (" + str(size) + " 字节)")


def index():
    """列出所有章节的索引（章节号、标题、字数、状态）。"""
    proj = S.load_project()
    titles = S.load_titles(proj)
    chapters = proj.list_chapters()
    if not chapters:
        console.print("[yellow]暂无章节。[/yellow]")
        return
    table = Table(title="全书索引")
    table.add_column("章节")
    table.add_column("标题")
    table.add_column("字数")
    table.add_column("状态")
    total = 0
    for c in chapters:
        n = int(c.stem)
        text = c.read_text(encoding="utf-8")
        wc = S.chapter_word_count(text)
        total += wc
        title = titles.get("%04d" % n, "（无）")
        if wc < 100:
            status = "[red]异常[/red]"
        elif "<think>" in text or " 区块" in text:
            status = "[red]残片[/red]"
        else:
            status = "[green]正常[/green]"
        table.add_row(str(n), title, str(wc), status)
    table.add_row("", "[bold]总计[/bold]", "[bold]" + str(total) + "[/bold]", "")
    console.print(table)


def register(app: typer.Typer) -> None:
    """注册所有输出类命令。"""
    app.command()(export)
    app.command()(index)
