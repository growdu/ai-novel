"""改编与同人命令：adapt / fanfic。

v0.12 后这两个命令仅生成改编方案 / 单章衍生作品，不进入端到端流水线。
要端到端用 `novel write --from-source`（替代了这两个的端到端作用）。
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from novel import generator as G
from novel import storage as S
from novel.config import load_global
from novel.llm import LLMClient


console = Console()


def adapt(
    source_file: str = typer.Option(None, "--source", "-s", help="源小说信息文件（txt/md）"),
    source_text: str = typer.Option("", "--text", "-t", help="直接输入源小说信息"),
    direction: str = typer.Option("换名 + 换壳", "--direction", "-d", help="改编方向：换名/换壳/后传/反派视角/性别转换"),
    target_genre: str = typer.Option("现实 / 严肃文学", "--genre", "-g"),
    target_style: str = typer.Option("冷峻 / 极简", "--style", "-y"),
    words: int = typer.Option(100000, "--words", "-w"),
    title: str = typer.Option(None, "--title", help="新小说标题"),
    save: bool = typer.Option(True, "--save/--print", help="保存到 .novel/adapt.md 还是只打印"),
    with_skeleton: bool = typer.Option(True, "--with-skeleton/--no-skeleton", help="是否先提取骨架"),
):
    """基于源小说（高热度小说）改编成新小说（仅生成改编方案；端到端用 `novel write --from-source`）。"""
    proj = S.load_project()
    cfg = load_global()
    client = LLMClient(cfg)
    src = source_text
    if source_file:
        p = Path(source_file)
        if not p.is_absolute():
            p = proj.root / source_file
        if p.exists():
            src = p.read_text(encoding="utf-8")
        else:
            console.print("[red]源文件不存在：%s[/red]" % p)
            raise typer.Exit(1)
    if not src.strip():
        console.print("[red]请用 --text 或 --source 提供源小说信息。[/red]")
        raise typer.Exit(1)
    skeleton_text = ""
    if with_skeleton:
        console.print("[bold]步骤 1/2: 提取源小说骨架...[/bold]")
        skeleton_text = G.extract_skeleton(src, client=client)
    console.print("[bold]步骤 2/2: 生成改编方案...[/bold]")
    adapt_text = G.adapt_novel(src, direction, target_genre, target_style, client=client, skeleton_text=skeleton_text)
    full_text = ""
    if skeleton_text:
        full_text = "# 源小说骨架\n\n" + skeleton_text + "\n\n---\n\n# 改编方案\n\n" + adapt_text
    else:
        full_text = adapt_text
    if save:
        out = proj.novel_dir / "adapt.md"
        out.write_text(full_text, encoding="utf-8")
        if title:
            proj.meta["title"] = title
        proj.meta["genre"] = target_genre
        proj.meta["style_preset"] = target_style
        proj.meta["source"] = source_file or "（用户输入）"
        from novel.storage import _write_yaml
        _write_yaml(proj.project_yaml, proj.meta)
        console.print("[green]已保存改编方案:[/green] " + str(out))
        console.print("\n[dim]下一步建议（端到端用 novel write --from-source）：[/dim]")
        console.print("  1. novel write demo --from-source " + str(source_file or "source.txt") + " --direction " + direction)
    else:
        console.print(Panel(full_text, title="改编方案"))


def fanfic(
    source_file: str = typer.Option(None, "--source", "-s", help="源小说信息文件"),
    source_text: str = typer.Option("", "--text", "-t", help="直接输入源小说信息"),
    ending: str = typer.Option("", "--ending", "-e", help="源小说结尾状态"),
    character: str = typer.Option("主角", "--char", "-c", help="视角人物"),
    era: str = typer.Option("后传：源小说结束后 5 年", "--era", help="故事时机"),
    words: int = typer.Option(3000, "--words", "-w"),
    save: bool = typer.Option(True, "--save/--print"),
    save_as_chapter: int = typer.Option(None, "--as-chapter", help="保存为指定章节号"),
):
    """写后传 / 番外 / 同人。基于已结束源小说写衍生作品。"""
    proj = S.load_project()
    cfg = load_global()
    client = LLMClient(cfg)
    src = source_text
    if source_file:
        p = Path(source_file)
        if not p.is_absolute():
            p = proj.root / source_file
        if p.exists():
            src = p.read_text(encoding="utf-8")
        else:
            console.print("[red]源文件不存在：%s[/red]" % p)
            raise typer.Exit(1)
    if not src.strip():
        console.print("[red]请用 --text 或 --source 提供源小说信息。[/red]")
        raise typer.Exit(1)
    console.print("[bold]写 " + character + " 的衍生故事...[/bold]")
    text = G.write_fanfic(src, ending, character, era, words, client=client)
    if save:
        if save_as_chapter is not None:
            S.save_chapter(proj, save_as_chapter, text)
            console.print("[green]已保存为第 " + str(save_as_chapter) + " 章[/green]")
        else:
            out = proj.novel_dir / ("fanfic_" + character.replace(" ", "_") + ".md")
            out.write_text(text, encoding="utf-8")
            console.print("[green]已保存到[/green] " + str(out))
    else:
        console.print(Panel(text, title=character + " - " + era))


def register(app: typer.Typer) -> None:
    """注册改编 / 同人命令。"""
    app.command()(adapt)
    app.command()(fanfic)
