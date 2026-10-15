"""预设查询命令：genres / styles / webnovel_genres / webnovel_styles / templates。

只读命令：列出所有支持的题材 / 文风 / 模板。
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table


console = Console()


def genres():
    """列出所有支持的题材（严肃向）。"""
    from novel.prompts import list_genres
    console.print("[bold]支持的题材（严肃向，10 个）[/bold]")
    for g in list_genres():
        console.print("  - " + g)


def styles():
    """列出所有支持的文风。"""
    from novel.prompts import list_styles
    console.print("[bold]支持的文风[/bold]（11 个）")
    for s in list_styles():
        console.print("  - " + s)


def webnovel_genres():
    """列出所有支持的网文题材（9 个）。"""
    from novel.prompts import list_webnovel_genres
    console.print("[bold]支持的网文题材（9 个）[/bold]")
    for g in list_webnovel_genres():
        console.print("  - " + g)


def webnovel_styles():
    """列出所有支持的网文爽感文风（10 个）。"""
    from novel.prompts import list_webnovel_styles
    console.print("[bold]支持的网文爽感文风（10 个）[/bold]")
    for s in list_webnovel_styles():
        console.print("  - " + s)


def templates():
    """列出推荐的题材 + 文风组合，一键 init 用。

    比 webnovel-pack 更灵活，适合严肃向项目快速起步。
    用 --template 参数直接套用模板：novel init demo --template 东北悬疑
    """
    from novel.templates import list_templates
    tpls = list_templates()
    table = Table(title="推荐模板（10 个）")
    table.add_column("模板名")
    table.add_column("题材")
    table.add_column("文风")
    table.add_column("字数")
    table.add_column("风格描述")
    for t in tpls:
        table.add_row(t.name, t.genre, t.style, f"{t.default_words // 1000}K", t.description)
    console.print(table)
    console.print("\n[dim]用法示例：[/dim]")
    console.print("  novel init my_novel --template 东北悬疑 --title '盘锦往事'")
    console.print("  novel init my_novel --template 网文经典 --words 1000000")
    console.print("  novel init my_novel --title '冬夜的灰' --genre 悬疑 --style 冷峻 --words 80000")


def register(app: typer.Typer) -> None:
    """注册所有预设查询命令到 typer.Typer 实例。"""
    app.command()(genres)
    app.command(name="styles")(styles)
    app.command(name="webnovel-genres")(webnovel_genres)
    app.command(name="webnovel-styles")(webnovel_styles)
    app.command()(templates)
