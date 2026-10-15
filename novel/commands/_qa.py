"""质量门控命令：polish / detect / radar。

auto 流水线阶段 3 会自动跑这些；这里是单章手动入口。
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


def polish(
    no: int = typer.Argument(...),
    extra: str = typer.Option("", "--extra", "-e"),
):
    """对已写章节做一次润色（去 AI 味）。"""
    proj = S.load_project()
    cfg = load_global()
    content = S.load_chapter(proj, no)
    if not content:
        console.print("[red]第 %d 章不存在。[/red]" % no)
        raise typer.Exit(1)
    outline_text = proj.outline_path.read_text(encoding="utf-8") if proj.outline_path.exists() else ""
    plan = G.parse_chapter_plan(outline_text, no)
    prev = S.load_chapter(proj, no - 1)
    prev_tail = prev[-500:] if prev else ""
    d_msgs = P.build_detect_messages(content)
    detect_report = LLMClient(cfg).chat(d_msgs, temperature=0.3).content
    console.print(Panel(detect_report[:1500], title="AI 味检测"))
    p_msgs = P.build_polish_messages(content, plan, prev_tail, detect_report, extra)
    res = LLMClient(cfg).chat(p_msgs, temperature=0.9)
    S.save_chapter(proj, no, res.content)
    console.print("[green]已润色并覆盖第 %d 章。原版本已备份到 history/。[/green]" % no)


def detect(
    no: int = typer.Argument(...),
    save_report: bool = typer.Option(False, "--save"),
):
    """只检测某章的 AI 味，不动正文。"""
    proj = S.load_project()
    cfg = load_global()
    content = S.load_chapter(proj, no)
    if not content:
        console.print("[red]第 %d 章不存在。[/red]" % no)
        raise typer.Exit(1)
    msgs = P.build_detect_messages(content)
    res = LLMClient(cfg).chat(msgs, temperature=0.3)
    console.print(Panel(res.content, title="第 %d 章 AI 味检测" % no))
    if save_report:
        p = proj.novel_dir / "reports" / ("detect_%04d.md" % no)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(res.content, encoding="utf-8")
        console.print("[green]报告已保存:[/green] %s" % p)


def radar(no: int = typer.Argument(..., help="章节号")):
    """风格雷达：量化某章与 samples 的风格相似度。"""
    proj = S.load_project()
    cfg = load_global()
    res = G.style_radar(proj, no, client=LLMClient(cfg))
    if res:
        console.print(Panel(res, title="第 %d 章风格雷达" % no))
    else:
        console.print("[red]第 %d 章不存在。[/red]" % no)


def register(app: typer.Typer) -> None:
    """注册所有 QA 类命令。"""
    app.command()(polish)
    app.command()(detect)
    app.command()(radar)
