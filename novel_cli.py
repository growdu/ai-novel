"""novel CLI thin entry（v0.13.x 模块化后）。

50 个命令按功能切到 novel/commands/{_config,_presets,_init,_run,
_planning,_writing,_qa,_state,_project,_diagnose,_output}.py。
本文件只剩 ~40 行：建 app + 注册全局 callback + 注册全部命令 + 入口。
"""
from __future__ import annotations

import typer
from rich.console import Console

from novel import __version__
from novel.commands import register_all


app = typer.Typer(
    help="AI 小说创作工具 · novel-writer " + __version__,
    no_args_is_help=True,
    add_completion=True,
    pretty_exceptions_enable=True,
    rich_markup_mode="rich",
    invoke_without_command=True,
)
console = Console()


@app.callback()
def _main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-V", help="显示版本号并退出", is_eager=True),
    verbose: bool = typer.Option(True, "--verbose/--quiet", "-v/-q"),
):
    """全局选项：--version / -V / --verbose / --quiet。"""
    if version:
        console.print(f"[bold]novel-writer[/bold] {__version__}")
        raise typer.Exit()
    ctx.obj = {"verbose": verbose}


# 一键注册全部命令（详见 novel/commands/__init__.py）
register_all(app)


if __name__ == "__main__":
    app()
