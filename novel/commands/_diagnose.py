"""诊断与修复命令：doctor / retry-stuck / rollback / fix / diff。

包含 novel 看护工具；用户跑完 auto 后视情况用。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from novel import generator as G
from novel import storage as S
from novel.config import load_global
from novel.llm import LLMClient
from novel import prompts as P


console = Console()


def doctor(
    fix: bool = typer.Option(False, "--fix", help="尝试自动修复可处理的问题（占位文件/缺失目录）"),
    json_output: bool = typer.Option(False, "--json", help="机器可读 JSON 输出"),
):
    """自动诊断项目状态：检查必要文件、配置、潜在问题。

    带 --fix 时会尝试自动处理可恢复的问题（创建缺失的目录、用占位文件填空白）。
    带 --json 时输出结构化报告，方便脚本消费。
    """
    proj = S.load_project()
    cfg = load_global()
    issues = []
    warnings = []
    ok = []
    auto_fixable = []

    def _record_fix(name, action):
        if fix:
            try:
                action()
                ok.append(f"[自动修复] {name}")
            except Exception as e:
                issues.append(f"[修复失败] {name}: {e}")
        else:
            auto_fixable.append(name)

    if not cfg.api_key:
        issues.append("[red]未设置 OPENAI_API_KEY[/red]（运行 [bold]novel setup[/bold] 或编辑 .env）")
    if cfg.target_chapter_words < 1000:
        warnings.append("目标章节字数偏少，建议 2500-5000")
    if cfg.temperature < 0.7:
        warnings.append("temperature 偏稳，可能缺少变化")
    if cfg.temperature > 1.1:
        warnings.append("temperature 偏高（>1.1），可能过于天马行空")

    def _ensure_placeholder(path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    if not proj.outline_path.exists() or proj.outline_path.stat().st_size < 100:
        _record_fix(
            "大纲缺失",
            lambda: _ensure_placeholder(proj.outline_path, "# 大纲\n\n（待生成；运行 novel outline）\n"),
        )
    if not proj.characters_path.exists() or proj.characters_path.stat().st_size < 100:
        _record_fix(
            "人物志缺失",
            lambda: _ensure_placeholder(proj.characters_path, "# 人物志\n\n（待生成；运行 novel characters）\n"),
        )
    if not proj.world_path.exists() or proj.world_path.stat().st_size < 100:
        _record_fix(
            "世界观缺失",
            lambda: _ensure_placeholder(proj.world_path, "# 世界观\n\n（待生成；运行 novel world）\n"),
        )
    if not proj.volumes_path.exists() or proj.volumes_path.stat().st_size < 100:
        _record_fix(
            "分卷缺失",
            lambda: _ensure_placeholder(proj.volumes_path, "# 分卷\n\n（待生成；运行 novel volumes）\n"),
        )
    if not proj.style_path.exists() or proj.style_path.stat().st_size < 100:
        _record_fix(
            "文风缺失",
            lambda: _ensure_placeholder(proj.style_path, "# 文风\n\n（待设置；运行 init 时加 --style）\n"),
        )
    chapters = proj.list_chapters()
    if not chapters:
        warnings.append("还没有写任何章节（运行 [bold]novel chapter 1[/bold]）")
    else:
        for c in chapters:
            text = c.read_text(encoding="utf-8") if c.exists() else ""
            wc = S.chapter_word_count(text)
            if wc < 100:
                issues.append(f"第 {c.stem} 章字数 {wc} 异常（可能生成失败；运行 [bold]novel retry-stuck[/bold]）")
    samples = list(proj.samples_dir.glob("*.md")) if proj.samples_dir.exists() else []
    samples = [s for s in samples if not s.name.startswith("_")]
    if not samples:
        warnings.append("samples/ 目录为空（放入作者手写片段可显著提升风格）")
    if chapters and len(chapters) >= 2:
        try:
            if proj.state_path.stat().st_size < 100:
                warnings.append("state.md 过小（应该 >= 100 字节；运行 [bold]novel state[/bold]）")
        except FileNotFoundError:
            warnings.append("state.md 缺失（运行 [bold]novel state[/bold]）")
        try:
            if proj.foreshadowing_path.stat().st_size < 100:
                warnings.append("foreshadowing.md 过小（运行 [bold]novel foreshadow[/bold]）")
        except FileNotFoundError:
            warnings.append("foreshadowing.md 缺失（运行 [bold]novel foreshadow[/bold]）")
    if not issues and not auto_fixable:
        ok.append("通过所有关键检查")
    if auto_fixable and not fix:
        warnings.append(f"{len(auto_fixable)} 项可自动处理（用 [bold]--fix[/bold]）")

    if json_output:
        import json
        report = {
            "issues": issues,
            "warnings": warnings,
            "ok": ok,
            "auto_fixable": auto_fixable,
            "project_root": str(proj.root),
            "title": proj.title,
        }
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return

    table = Table(title="novel doctor 诊断报告")
    table.add_column("状态")
    table.add_column("条数")
    table.add_row("[red]问题[/red]", str(len(issues)))
    table.add_row("[yellow]警告[/yellow]", str(len(warnings)))
    table.add_row("[cyan]可自动修复[/cyan]", str(len(auto_fixable)))
    table.add_row("[green]通过[/green]", str(len(ok)))
    console.print(table)
    if issues:
        console.print("\n[red]问题（必须修复）[/red]")
        for i, s in enumerate(issues, 1):
            console.print("  " + str(i) + ". " + s)
    if warnings:
        console.print("\n[yellow]警告（建议改进）[/yellow]")
        for i, s in enumerate(warnings, 1):
            console.print("  " + str(i) + ". " + s)
    if ok and not issues and not warnings:
        console.print("\n[green]✓ " + ok[0] + "[/green]")
    if auto_fixable and not fix:
        console.print(f"\n[dim]提示：运行 [bold]novel doctor --fix[/bold] 自动处理 {len(auto_fixable)} 项[/dim]")


def retry_stuck(
    threshold: int = typer.Option(100, "--threshold", help="字数低于此视为异常"),
    dry: bool = typer.Option(False, "--dry", help="只列出异常章节不重写"),
    iters: int = typer.Option(1, "--iters", "-i"),
):
    """检测并自动重写异常章节（0 字节 / 残片 / 字数过少）。"""
    proj = S.load_project()
    cfg = load_global()
    stuck = G.find_stuck_chapters(proj, threshold=threshold)
    if not stuck:
        console.print("[green]所有章节均正常。[/green]")
        return
    console.print("[bold]发现 " + str(len(stuck)) + " 个异常章节：[/bold]")
    for n, wc, text in stuck:
        flag = "（含 think 残片）" if "<think>" in text or " 区块" in text else ""
        console.print("  第 " + str(n) + " 章: " + str(wc) + " 字 " + flag)
    if dry:
        return
    console.print("\n开始重写...")
    client = LLMClient(cfg)
    for n, wc, text in stuck:
        target = proj.chapters_dir / ("%04d.md" % n)
        if target.exists() and text:
            S.save_chapter(proj, n, text, backup=True)
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        console.print("\n[bold]重写第 " + str(n) + " 章...[/bold]")
        ctx = {
            "title": proj.title,
            "outline": proj.outline_path.read_text(encoding="utf-8") if proj.outline_path.exists() else "",
            "characters": proj.characters_path.read_text(encoding="utf-8") if proj.characters_path.exists() else "",
            "style": proj.style_path.read_text(encoding="utf-8") if proj.style_path.exists() else "",
            "genre": proj.meta.get("genre", ""),
            "chapter_plan": G.parse_chapter_plan(proj.outline_path.read_text(encoding="utf-8") if proj.outline_path.exists() else "", n),
            "prev_chapter_tail": (S.load_chapter(proj, n - 1) or "")[-500:],
            "state": proj.state_path.read_text(encoding="utf-8") if proj.state_path.exists() else "",
            "foreshadow": proj.foreshadowing_path.read_text(encoding="utf-8") if proj.foreshadowing_path.exists() else "",
            "world": proj.world_path.read_text(encoding="utf-8") if proj.world_path.exists() else "",
            "timeline": proj.timeline_path.read_text(encoding="utf-8") if proj.timeline_path.exists() else "",
            "volumes": proj.volumes_path.read_text(encoding="utf-8") if proj.volumes_path.exists() else "",
            "arc": (proj.arcs_dir / "_overview.md").read_text(encoding="utf-8") if (proj.arcs_dir / "_overview.md").exists() else "",
        }
        req = G.ChapterRequest(chapter_no=n, target_words=cfg.target_chapter_words)
        res = G.write_chapter_extended(req, ctx, project=proj, client=client, max_iters=iters, update_after=False, verbose=True)
        S.save_chapter(proj, n, res.content)
        new_wc = S.chapter_word_count(res.content)
        console.print("[green]已重写第 " + str(n) + " 章，新字数 " + str(new_wc) + "[/green]")
    console.print("\n[bold]重写完成。建议跑 novel audit 再次确认。[/bold]")


def rollback(
    no: int = typer.Argument(..., help="章节号"),
    to_version: str = typer.Option(None, "--to", help="回滚到哪个版本"),
    list_only: bool = typer.Option(False, "--list", "-l", help="只列出历史版本"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
):
    """把当前章节回滚到指定历史版本（备份当前为新版本）。

    回滚前会显示 diff 摘要；用 --yes 跳过交互确认（适合脚本）。
    """
    proj = S.load_project()
    if list_only:
        files = sorted(proj.history_dir.glob("chapter_%04d_v*.md" % no)) if proj.history_dir.exists() else []
        if not files:
            console.print("[yellow]无历史版本。[/yellow]")
            return
        console.print("[bold]第 " + str(no) + " 章历史版本[/bold]")
        for f in files:
            t = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))
            console.print("  " + f.stem + "  " + str(f.stat().st_size) + "字节  " + t)
        return
    if to_version is None:
        console.print("[red]请指定 --to v1 / v2 ... 或 --list。[/red]")
        raise typer.Exit(1)
    target = proj.history_dir / ("chapter_%04d_%s.md" % (no, to_version))
    if not target.exists():
        console.print("[red]版本 %s 不存在。[/red]" % to_version)
        raise typer.Exit(1)
    current = S.load_chapter(proj, no)
    if current:
        from novel.diff_utils import stats_diff
        st = stats_diff(current, target.read_text(encoding="utf-8"))
        console.print(f"[dim]差异统计：新增 {st['added']} 行 / 删除 {st['removed']} 行 / 相似度 {st['similarity']*100:.1f}%[/dim]")
    if not yes and not Confirm.ask(
        f"确认把第 {no} 章回滚到 {to_version}？当前内容会备份为新历史版本。",
        default=False,
    ):
        console.print("[yellow]已取消。[/yellow]")
        raise typer.Exit()
    if current:
        S.save_chapter(proj, no, current, backup=True)
    target_text = target.read_text(encoding="utf-8")
    S.save_chapter(proj, no, target_text, backup=False)
    console.print(f"[green]✓ 已回滚第 {no} 章到 {to_version}。回滚前内容已备份为新版本。[/green]")


def fix(
    no: int = typer.Argument(..., help="章节号"),
    dry: bool = typer.Option(True, "--dry/--no-dry", help="只检查不修复（默认 dry）"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
):
    """检测并修复异常章节（0 字节 / 过短 / 残片）。

    默认 dry 模式只打印建议，不动正文。要回滚动作加 --no-dry -y。
    """
    proj = S.load_project()
    target = proj.chapters_dir / ("%04d.md" % no)
    if not target.exists():
        console.print("[red]第 " + str(no) + " 章不存在。[/red]")
        return
    text = target.read_text(encoding="utf-8")
    wc = S.chapter_word_count(text)
    issues = []
    if wc < 100:
        issues.append("字数过少（" + str(wc) + " 字）")
    if "<think>" in text:
        issues.append("包含未剥 think 标签")
    if " 区块" in text:
        issues.append("包含 think 残片")
    if "OK so" in text[:200] or "Let me" in text[:200]:
        issues.append("包含英文 think 残片")
    if issues:
        console.print(f"[yellow]第 {no} 章异常：[/yellow]")
        for i, s in enumerate(issues, 1):
            console.print("  " + str(i) + ". " + s)
        if not dry:
            console.print(f"\n[dim]建议：rm {target} && novel chapter {no} 重写[/dim]")
            if not yes and not Confirm.ask("按上述建议删除并重写？", default=False):
                console.print("[yellow]已取消。请手动处理。[/yellow]")
                raise typer.Exit()
            target.unlink()
            console.print(f"[green]✓ 已删除 {target}。请运行 novel chapter {no} 重写。[/green]")
    else:
        console.print(f"[green]第 {no} 章正常（{wc} 字）。[/green]")


def diff(
    no: int = typer.Argument(..., help="章节号"),
    ver_a: str = typer.Option(None, "--from", "-a", help="版本 A（章节号或版本号）"),
    ver_b: str = typer.Option(None, "--to", "-b", help="版本 B（章节号或版本号）"),
    stats_only: bool = typer.Option(False, "--stats", help="只显示统计"),
    context: int = typer.Option(3, "--context", "-c", help="显示多少行上下文"),
):
    """对比两版章节的差异。"""
    proj = S.load_project()
    if ver_a is None and ver_b is None:
        ver_a = "current"
        ver_b = "last"
    if ver_b == "last":
        ver_b = None
    from novel.diff_utils import unified_diff, stats_diff
    current = S.load_chapter(proj, no)
    if current is None:
        console.print("[red]第 %d 章不存在。[/red]" % no)
        raise typer.Exit(1)
    hist_files = sorted(proj.history_dir.glob("chapter_%04d_v*.md" % no)) if proj.history_dir.exists() else []
    if ver_a is None:
        a_text = current
        a_name = "current"
    elif ver_a.lower() == "current":
        a_text = current
        a_name = "current"
    elif ver_a.isdigit():
        target = proj.chapters_dir / ("%04d.md" % int(ver_a))
        if not target.exists():
            console.print("[red]第 %d 章不存在。[/red]" % int(ver_a))
            raise typer.Exit(1)
        a_text = target.read_text(encoding="utf-8")
        a_name = "chapter %04d" % int(ver_a)
    else:
        target = proj.history_dir / ("chapter_%04d_%s.md" % (no, ver_a))
        if not target.exists():
            console.print("[red]版本 %s 不存在。[/red]" % ver_a)
            raise typer.Exit(1)
        a_text = target.read_text(encoding="utf-8")
        a_name = ver_a
    if ver_b is None:
        if hist_files:
            b_text = hist_files[-1].read_text(encoding="utf-8")
            b_name = hist_files[-1].name
        else:
            console.print("[yellow]没有历史版本可对比。[/yellow]")
            raise typer.Exit(1)
    elif ver_b.lower() == "current":
        b_text = current
        b_name = "current"
    elif ver_b.isdigit():
        target = proj.chapters_dir / ("%04d.md" % int(ver_b))
        if not target.exists():
            console.print("[red]第 %d 章不存在。[/red]" % int(ver_b))
            raise typer.Exit(1)
        b_text = target.read_text(encoding="utf-8")
        b_name = "chapter %04d" % int(ver_b)
    else:
        target = proj.history_dir / ("chapter_%04d_%s.md" % (no, ver_b))
        if not target.exists():
            console.print("[red]版本 %s 不存在。[/red]" % ver_b)
            raise typer.Exit(1)
        b_text = target.read_text(encoding="utf-8")
        b_name = ver_b
    stats = stats_diff(a_text, b_text)
    console.print("[bold]对比 " + a_name + " -> " + b_name + "[/bold]")
    console.print("  新增行: %d  删除行: %d  相同行: %d  相似度: %.1f%%" % (
        stats["added"], stats["removed"], stats["same"], stats["similarity"] * 100))
    if not stats_only:
        d = unified_diff(a_text, b_text, a_name, b_name, n=context)
        if d:
            console.print()
            for line in d.splitlines()[:200]:
                console.print(line)
            if len(d.splitlines()) > 200:
                console.print("\n[dim]... 以下省略（用 --context 调大）[/dim]")
        else:
            console.print("\n[green]两版本完全一致。[/green]")


def register(app: typer.Typer) -> None:
    """注册所有诊断 / 修复命令。"""
    app.command()(doctor)
    app.command(name="retry-stuck")(retry_stuck)
    app.command()(rollback)
    app.command()(fix)
    app.command()(diff)
