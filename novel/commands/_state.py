"""长期记忆命令：timeline / volume_report / state / rolling / check / arc / foreshadow / gaps。

长篇自动维护系统的「状态摘要层」；与 novel/auto.py 阶段 1 协同。
"""
from __future__ import annotations

import re

import typer
from rich.console import Console
from rich.table import Table

from novel import generator as G
from novel import storage as S
from novel.config import load_global
from novel.llm import LLMClient


console = Console()


def timeline():
    """基于大纲+已写章节，维护故事内时间线。"""
    proj = S.load_project()
    cfg = load_global()
    G.generate_timeline(proj, client=LLMClient(cfg))
    console.print("[green]已保存[/green] " + str(proj.timeline_path))


def volume_report(volume: int = typer.Option(1, "--volume", "-v", help="第几卷")):
    """生成指定卷的卷末报告。"""
    proj = S.load_project()
    cfg = load_global()
    G.generate_volume_report(proj, client=LLMClient(cfg), volume_no=volume)
    console.print("[green]已保存[/green] " + str(proj.novel_dir / "reports" / ("volume_%02d_report.md" % volume)))


def state():
    """手动刷新故事状态摘要（每章写完会自动更新）。"""
    proj = S.load_project()
    cfg = load_global()
    G.update_state(proj, client=LLMClient(cfg))
    console.print("[green]已保存[/green] " + str(proj.state_path))


def rolling():
    """手动刷新全书滚动摘要。"""
    proj = S.load_project()
    cfg = load_global()
    G.update_rolling_summary(proj, client=LLMClient(cfg))
    console.print("[green]已保存[/green] " + str(proj.rolling_summary_path))


def check(lookback: int = typer.Option(10, "--lookback", "-k")):
    """跨章节一致性检查。"""
    proj = S.load_project()
    cfg = load_global()
    G.check_consistency(proj, client=LLMClient(cfg), lookback=lookback)
    console.print("[green]已保存[/green] " + str(proj.novel_dir / "consistency_report.md"))


def arc(
    character: str = typer.Option(None, "--char", "-c", help="指定查看某个人物"),
    only: bool = typer.Option(False, "--only", help="只显示指定人物"),
):
    """刷新人物弧线总览（也可指定查看某个人物）。"""
    proj = S.load_project()
    cfg = load_global()
    G.update_arc(proj, client=LLMClient(cfg))
    overview = proj.arcs_dir / "_overview.md"
    console.print("[green]已保存[/green] " + str(overview))
    if character:
        text = overview.read_text(encoding="utf-8")
        if only:
            pattern = re.compile(r"^##\s+" + re.escape(character) + r"\s*$([\s\S]*?)(?=^##\s+|\Z)", re.MULTILINE)
            m = pattern.search(text)
            if m:
                from rich.panel import Panel
                console.print(Panel(m.group(1).strip(), title=character + " 弧线"))
            else:
                console.print("[yellow]未找到人物 " + character + "[/yellow]")
        else:
            for line in text.splitlines():
                if character in line:
                    console.print(line, style="bold")
                else:
                    console.print(line)


def foreshadow():
    """刷新伏笔簿。"""
    proj = S.load_project()
    cfg = load_global()
    G.update_foreshadow(proj, client=LLMClient(cfg))
    console.print("[green]已保存[/green] " + str(proj.foreshadowing_path))


def gaps():
    """列出所有未回收的伏笔，及其预计回收章节是否已过。"""
    proj = S.load_project()
    text = proj.foreshadowing_path.read_text(encoding="utf-8") if proj.foreshadowing_path.exists() else ""
    if not text:
        console.print("[yellow]伏笔簿为空。[/yellow]")
        return
    chapters = proj.list_chapters()
    last_no = max(int(c.stem) for c in chapters) if chapters else 0
    pattern = re.compile(r"\[F(\d+)\][\s\S]{0,200}?回收[：:]?[\s\S]{0,40}?第\s*(\d+)\s*章")
    overdue = []
    upcoming = []
    fulfilled = []
    for m in pattern.finditer(text):
        n = int(m.group(1))
        try:
            target = int(m.group(2))
        except ValueError:
            continue
        if target <= last_no:
            fulfilled.append((n, target))
        else:
            upcoming.append((n, target))
    open_pattern = re.compile(r"\[F(\d+)\][^。\n]*?未回收", re.MULTILINE)
    for m in open_pattern.finditer(text):
        n = int(m.group(1))
        overdue.append(n)
    table = Table(title="伏笔状态")
    table.add_column("状态")
    table.add_column("条数")
    table.add_column("F 编号")
    table.add_row("[red]未回收（应当回收）[/red]", str(len(overdue)), ", ".join("F" + str(x) for x in overdue))
    table.add_row("[yellow]待回收（尚未到章节）[/yellow]", str(len(upcoming)), ", ".join("F" + str(x) + "(到" + str(t) + "章)" for x, t in upcoming))
    table.add_row("[green]已到回收章节[/green]", str(len(fulfilled)), ", ".join("F" + str(x) + "(目标" + str(t) + "章)" for x, t in fulfilled))
    console.print(table)
    if overdue:
        console.print("\n[red]警告：以下伏笔已过预计回收章节：[/red]")
        for n in overdue:
            console.print("  F" + str(n))


def register(app: typer.Typer) -> None:
    """注册所有长期记忆类命令。"""
    app.command()(timeline)
    app.command()(volume_report)
    app.command()(state)
    app.command()(rolling)
    app.command()(check)
    app.command()(arc)
    app.command()(foreshadow)
    app.command()(gaps)
