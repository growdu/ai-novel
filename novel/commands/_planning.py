"""规划命令：outline / characters / world / volumes。

长篇自动维护系统的一部分；run_auto_novel 会自动调这些。
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

from novel import generator as G
from novel import storage as S
from novel.config import load_global
from novel.llm import LLMClient
from novel import prompts as P


console = Console()


def outline(
    genre: str = typer.Option(None, "--genre", "-g"),
    words: int = typer.Option(None, "--words", "-w"),
    extra: str = typer.Option("", "--extra", "-e"),
    save: bool = typer.Option(True, "--save/--print"),
):
    """生成或重写全书大纲。"""
    proj = S.load_project()
    cfg = load_global()
    characters = proj.characters_path.read_text(encoding="utf-8") if proj.characters_path.exists() else ""
    existing = proj.outline_path.read_text(encoding="utf-8") if proj.outline_path.exists() else ""
    title = proj.title
    theme = proj.meta.get("theme", existing or "")
    g_ = genre or proj.meta.get("genre", "现实")
    w_ = words or proj.meta.get("target_words", 30000)
    msgs = P.build_outline_messages(title, theme, g_, w_, characters, extra)
    res = LLMClient(cfg).chat(msgs, temperature=0.85)
    if save:
        proj.outline_path.write_text("# 大纲\n\n" + res.content + "\n", encoding="utf-8")
        console.print("[green]已保存到[/green] %s" % proj.outline_path)
    else:
        console.print(Panel(res.content, title="大纲（未保存）"))


def characters(
    extra: str = typer.Option("", "--extra", "-e"),
    save: bool = typer.Option(True, "--save/--print"),
):
    """基于大纲生成或扩展人物志。"""
    proj = S.load_project()
    cfg = load_global()
    outline_text = proj.outline_path.read_text(encoding="utf-8") if proj.outline_path.exists() else ""
    existing = proj.characters_path.read_text(encoding="utf-8") if proj.characters_path.exists() else ""
    msgs = P.build_character_messages(outline_text, existing, extra)
    res = LLMClient(cfg).chat(msgs, temperature=0.85)
    if save:
        proj.characters_path.write_text("# 人物志\n\n" + res.content + "\n", encoding="utf-8")
        console.print("[green]已保存到[/green] %s" % proj.characters_path)
    else:
        console.print(Panel(res.content, title="人物志（未保存）"))


def world():
    """生成世界观设定（基于大纲与主题）。"""
    proj = S.load_project()
    cfg = load_global()
    theme = proj.meta.get("theme", "")
    genre = proj.meta.get("genre", "现实")
    G.generate_world(proj, theme, genre, client=LLMClient(cfg))
    console.print("[green]已保存[/green] " + str(proj.world_path))


def volumes():
    """分卷（长篇分多卷）。"""
    proj = S.load_project()
    cfg = load_global()
    G.generate_volumes(proj, client=LLMClient(cfg))
    console.print("[green]已保存[/green] " + str(proj.volumes_path))


def register(app: typer.Typer) -> None:
    """注册所有规划类命令。"""
    app.command()(outline)
    app.command(name="characters")(characters)
    app.command(name="world")(world)
    app.command(name="volumes")(volumes)
