"""手动写作命令：chapter / continue / chat / expand_scene / title。

属于「高级手动」操作（v0.12 后不再推荐主流程用，但仍是局部微调工具）。
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

from novel import generator as G
from novel import storage as S
from novel.config import load_global
from novel.llm import LLMClient


console = Console()


def chapter(
    no: int = typer.Argument(..., help="章节号，从 1 开始"),
    words: int = typer.Option(None, "--words", "-w"),
    iters: int = typer.Option(2, "--iters", "-i"),
    no_polish: bool = typer.Option(False, "--no-polish"),
    extra: str = typer.Option("", "--extra", "-e"),
):
    """生成指定的一章（手动覆盖单章时用）。"""
    proj = S.load_project()
    cfg = load_global()
    outline_text = proj.outline_path.read_text(encoding="utf-8") if proj.outline_path.exists() else ""
    characters_text = proj.characters_path.read_text(encoding="utf-8") if proj.characters_path.exists() else ""
    style = proj.style_path.read_text(encoding="utf-8") if proj.style_path.exists() else ""
    genre = proj.meta.get("genre", "")
    plan = G.parse_chapter_plan(outline_text, no)
    prev = S.load_chapter(proj, no - 1)
    prev_tail = prev[-500:] if prev else ""
    ctx = {
        "title": proj.title,
        "outline": outline_text,
        "characters": characters_text,
        "style": style,
        "genre": genre,
        "chapter_plan": plan,
        "prev_chapter_tail": prev_tail,
        "state": proj.state_path.read_text(encoding="utf-8") if proj.state_path.exists() else "",
        "foreshadow": proj.foreshadowing_path.read_text(encoding="utf-8") if proj.foreshadowing_path.exists() else "",
        "world": proj.world_path.read_text(encoding="utf-8") if proj.world_path.exists() else "",
        "timeline": proj.timeline_path.read_text(encoding="utf-8") if proj.timeline_path.exists() else "",
        "volumes": proj.volumes_path.read_text(encoding="utf-8") if proj.volumes_path.exists() else "",
        "arc": (proj.arcs_dir / "_overview.md").read_text(encoding="utf-8") if (proj.arcs_dir / "_overview.md").exists() else "",
    }
    req = G.ChapterRequest(chapter_no=no, target_words=words or cfg.target_chapter_words)
    client = LLMClient(cfg)
    res = G.write_chapter_extended(req, ctx, project=proj, client=client, max_iters=iters, update_after=True, verbose=True, do_polish=not no_polish)
    path = S.save_chapter(proj, no, res.content)
    console.print("[green]已保存[/green] %s | 字数 %d | 迭代 %d 轮" % (path, res.word_count, res.iterations))
    if res.detect_report:
        console.print(Panel(res.detect_report[:1500], title="AI 味检测（节选）"))
    if res.review_report:
        console.print(Panel(res.review_report[:1500], title="审稿（节选）"))


def continue_cmd(
    no: int = typer.Argument(..., help="章节号"),
    instruction: str = typer.Option("", "--with", "-w", help="作者意图"),
    words: int = typer.Option(1200, "--words", help="目标字数"),
):
    """在已有章节末尾接写一段新内容。"""
    proj = S.load_project()
    cfg = load_global()
    res = G.continue_chapter(proj, no, instruction, client=LLMClient(cfg), target_words=words)
    if res is None:
        console.print("[red]第 %d 章不存在。[/red]" % no)
    else:
        wc = S.chapter_word_count(res)
        total = S.chapter_word_count(S.load_chapter(proj, no) or "")
        console.print("[green]已接写 %d 字，章节总字数：%d[/green]" % (wc, total))


def chat(
    no: int = typer.Argument(..., help="章节号"),
    message: str = typer.Argument(..., help="作者自然语言指令"),
):
    """协作修改助手：让 AI 按你的自然语言指令修改某章。"""
    proj = S.load_project()
    cfg = load_global()
    res = G.chat_assistant(proj, no, message, client=LLMClient(cfg))
    if res is None:
        console.print("[red]第 %d 章不存在。[/red]" % no)
    else:
        wc = S.chapter_word_count(res)
        console.print("[green]已修改第 %d 章，新字数：%d[/green]" % (no, wc))


def expand_scene(
    no: int = typer.Argument(..., help="章节号"),
    after: str = typer.Option(..., "--after", "-a", help="在哪个句子之后接写"),
    instruction: str = typer.Option("", "--with", "-w", help="作者意图"),
    words: int = typer.Option(800, "--words", help="目标字数"),
):
    """交互式扩展：在指定位置后接写一段新场景。"""
    proj = S.load_project()
    cfg = load_global()
    res = G.expand_scene(proj, no, after, instruction, client=LLMClient(cfg), target_words=words)
    if res is None:
        console.print("[red]未找到 --after 指定的那句话。检查章节 %d 内容。[/red]" % no)
    else:
        wc = S.chapter_word_count(res)
        total = S.chapter_word_count(S.load_chapter(proj, no) or "")
        console.print("[green]已插入新场景，%d 字。章节总字数：%d[/green]" % (wc, total))


def title(no: int = typer.Argument(..., help="章节号"), force: bool = typer.Option(False, "--force", help="重新生成")):
    """为指定章节生成标题。"""
    proj = S.load_project()
    cfg = load_global()
    t = G.generate_chapter_title(proj, no, client=LLMClient(cfg), force=force)
    if t:
        console.print("[green]第 %d 章标题:[/green] %s" % (no, t))
    else:
        console.print("[red]第 %d 章不存在。[/red]" % no)


def register(app: typer.Typer) -> None:
    """注册所有写作类手动命令。"""
    app.command()(chapter)
    app.command(name="continue")(continue_cmd)
    app.command()(chat)
    app.command(name="expand-scene")(expand_scene)
    app.command()(title)
