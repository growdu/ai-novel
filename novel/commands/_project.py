"""项目信息与查询命令：list / info / whereami / status / audit / progress / history。

只读命令（除 _watch_status 是 streaming 展示）。集中放在「项目级」层。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from novel import storage as S


console = Console()


def _print_auto_status(proj):
    """--auto 单次输出 auto 状态表。"""
    from novel.auto_state import AutoState
    state = AutoState.load(proj.root)
    t = Table(title=f"auto · {proj.title}", show_header=False)
    t.add_column("指标")
    t.add_column("值")
    if state is None:
        t.add_row("状态", "未运行 novel auto")
    else:
        t.add_row("阶段", state.phase.value)
        if state.chapters_total:
            t.add_row("已完成", f"{len(state.chapters_done)}/{state.chapters_total}")
        t.add_row("累计字数", f"{state.total_words:,}")
        t.add_row("累计 token", f"{state.cumulative_tokens:,}")
        if state.cumulative_cost_cny > 0:
            cost_str = f"¥{state.cumulative_cost_cny:.3f}"
            if state.budget_cny > 0:
                cost_str += f" / ¥{state.budget_cny:.2f}"
            t.add_row("成本", cost_str)
        elapsed = int(state.updated_at - state.started_at)
        h, m, sec = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        t.add_row("用时", f"{h}:{m:02d}:{sec:02d}")
    console.print(t)


def _watch_status(proj, interval: float = 2.0, auto_only: bool = False):
    """持续刷新状态表。Ctrl-C 退出。"""
    from novel.auto_state import AutoState

    console.print(f"[dim]每 {interval}s 刷新一次 · Ctrl-C 退出[/dim]")

    def build_live_table() -> Table:
        if auto_only:
            state = AutoState.load(proj.root)
            t = Table(title=f"auto · {proj.title}", show_header=True)
            t.add_column("指标")
            t.add_column("值")
            if state is None:
                t.add_row("状态", "未运行 novel auto")
                return t
            t.add_row("阶段", state.phase.value)
            t.add_row("已完成", f"{len(state.chapters_done)}/{state.chapters_total}")
            t.add_row("累计字数", f"{state.total_words:,}")
            t.add_row("累计 token", f"{state.cumulative_tokens:,}")
            if state.cumulative_cost_cny > 0:
                cost_str = f"¥{state.cumulative_cost_cny:.3f}"
                if state.budget_cny > 0:
                    cost_str += f" / ¥{state.budget_cny:.2f}"
                t.add_row("成本", cost_str)
            elapsed = int(state.updated_at - state.started_at)
            h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
            t.add_row("用时", f"{h}:{m:02d}:{s:02d}")
            return t

        # 默认：简化版 status + auto 信息
        t = Table(title=f"项目: {proj.title}", show_header=False)
        t.add_column("项")
        t.add_column("值")
        state = AutoState.load(proj.root)
        if state:
            t.add_row("auto 阶段", state.phase.value)
            if state.chapters_total:
                t.add_row("auto 进度", f"{len(state.chapters_done)}/{state.chapters_total}")
            if state.cumulative_cost_cny > 0:
                t.add_row("auto 成本", f"¥{state.cumulative_cost_cny:.3f}")
        return t

    with Live(build_live_table(), refresh_per_second=1 / max(0.5, interval), console=console) as live:
        try:
            while True:
                time.sleep(interval)
                live.update(build_live_table())
        except KeyboardInterrupt:
            console.print("[dim]已停止 watch[/dim]")


def list_cmd(
    path: str = typer.Option(".", "--path", "-p", help="搜索起点目录"),
    depth: int = typer.Option(3, "--depth", "-d", help="最多向下搜索几层"),
):
    """列出指定目录（含子目录）下所有 novel 项目。"""
    base = Path(path).resolve()
    if not base.exists():
        console.print(f"[red]目录不存在：[/red] {base}")
        raise typer.Exit(1)
    projects = set()
    if depth < 1:
        depth = 1
    for novel_dir in base.glob("**/.novel"):
        rel = novel_dir.relative_to(base)
        parts = [p for p in rel.parts if p != ".novel"]
        if len(parts) > depth:
            continue
        if any(part.startswith(".") and part not in (".novel",) for part in rel.parts):
            continue
        projects.add(novel_dir.parent)
    projects = sorted(projects, key=lambda x: str(x))
    if not projects:
        console.print(f"[yellow]在 {base}（深度 {depth}）下没有找到任何 .novel 项目。[/yellow]")
        return
    table = Table(title=f"找到 {len(projects)} 个项目")
    table.add_column("标题")
    table.add_column("题材")
    table.add_column("字数目标")
    table.add_column("路径")
    for p in projects:
        meta_path = p / ".novel" / "project.yaml"
        title = p.name
        genre = ""
        words = ""
        if meta_path.exists():
            try:
                import yaml
                data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
                title = data.get("title", title)
                genre = data.get("genre", "")
                w = data.get("target_words", 0)
                words = f"{w // 1000}K" if w else ""
            except Exception:
                pass
        table.add_row(title, genre, words, str(p))
    console.print(table)


def info(
    name: str = typer.Argument(..., help="项目目录名（相对于当前目录或绝对路径）"),
):
    """查看指定项目的元信息，不需要 cd 进项目。"""
    p = Path(name)
    if not p.is_absolute():
        p = (Path.cwd() / name).resolve()
    novel_dir = p / ".novel"
    if not novel_dir.exists():
        console.print(f"[red]{p} 不是 novel 项目目录（缺少 .novel/）。[/red]")
        raise typer.Exit(1)
    try:
        import yaml
        meta = yaml.safe_load((novel_dir / "project.yaml").read_text(encoding="utf-8")) or {}
    except Exception as e:
        console.print(f"[red]project.yaml 解析失败：{e}[/red]")
        raise typer.Exit(1) from None
    table = Table(title=f"{meta.get('title', p.name)}")
    table.add_column("项")
    table.add_column("值")
    table.add_row("路径", str(p))
    table.add_row("题材", meta.get("genre", "未设置"))
    table.add_row("文风预设", meta.get("style_preset", "未设置") or "(自由)")
    table.add_row("目标字数", str(meta.get("target_words", "未设置")))
    table.add_row("主题", meta.get("theme", "未设置")[:200])
    chapters = list((novel_dir / "chapters").glob("[0-9]*.md")) if (novel_dir / "chapters").exists() else []
    table.add_row("已写章节", str(len(chapters)))
    table.add_row("最后修改", str(meta.get("source", ""))[:80])
    console.print(table)
    if chapters:
        console.print(f"\n[dim]cd {p} && novel status 查看详情[/dim]")


def whereami():
    """显示当前所在的项目路径与元信息（不要求在项目里）。"""
    from novel.config import find_project_root
    proj_root = find_project_root()
    if proj_root is None:
        console.print("[yellow]当前目录不在任何 novel 项目内。[/yellow]")
        console.print(f"  当前路径: {Path.cwd()}")
        console.print("  解决：[bold]novel init[/bold] 新建项目，或 [bold]cd[/bold] 进入已有项目")
        return
    try:
        proj = S.load_project(proj_root)
    except Exception as e:
        console.print(f"[red]找到项目但加载出错：{e}[/red]")
        return
    console.print(Panel.fit(
        f"[green]{proj.title}[/green]\n[dim]{proj.root}[/dim]",
        title="当前项目",
        border_style="green",
    ))


def status(
    watch: bool = typer.Option(False, "--watch", "-w", help="每 2 秒刷新一次（无需浏览器）"),
    interval: float = typer.Option(2.0, "--interval", help="--watch 模式的刷新间隔（秒）"),
    auto_only: bool = typer.Option(False, "--auto", help="只显示 novel auto 的状态（章节进度 + 成本）"),
):
    """查看当前项目的状态。--watch 持续刷新表格，无需 Web 仪表盘。"""
    proj = S.load_project()
    table = Table(title="项目: %s" % proj.title)
    table.add_column("项")
    table.add_column("值")
    table.add_row("路径", str(proj.root))
    table.add_row("类型", str(proj.meta.get("genre", "未设置")))
    table.add_row("主题", str(proj.meta.get("theme", "未设置")))
    table.add_row("目标总字数", str(proj.meta.get("target_words", "未设置")))

    def _is_set(p, threshold=50):
        try:
            return p.exists() and p.stat().st_size > threshold
        except Exception:
            return False

    table.add_row("大纲", "已生成" if _is_set(proj.outline_path) else "未生成（占位或未生成）")
    table.add_row("人物志", "已生成" if _is_set(proj.characters_path) else "未生成（占位或未生成）")
    table.add_row("文风", "已设置" if _is_set(proj.style_path, 30) else "未设置")
    table.add_row("世界观", "已生成" if _is_set(proj.world_path) else "未生成")
    table.add_row("分卷", "已生成" if _is_set(proj.volumes_path) else "未生成")
    table.add_row("时间线", "已生成" if _is_set(proj.timeline_path) else "未生成")
    table.add_row("故事状态", "已生成" if _is_set(proj.state_path) else "未生成")
    table.add_row("人物弧线", "已生成" if _is_set(proj.arcs_dir / "_overview.md") else "未生成")
    table.add_row("伏笔簿", "已生成" if _is_set(proj.foreshadowing_path) else "未生成")
    chapters = proj.list_chapters()
    table.add_row("已写章节数", str(len(chapters)))
    for ch in chapters:
        text = ch.read_text(encoding="utf-8")
        wc = S.chapter_word_count(text)
        table.add_row("  - " + ch.name, str(wc) + " 字")
    console.print(table)

    if auto_only:
        _print_auto_status(proj)

    if watch:
        _watch_status(proj, interval=interval, auto_only=auto_only)


def audit(
    start: int = typer.Option(1, "--start", "-s", help="起始章节"),
    end: int = typer.Option(None, "--end", "-e", help="结束章节（默认最后一章）"),
):
    """对所有章节做综合审计：字数 + 异常 + AI 味 + 雷达。"""
    proj = S.load_project()
    chapters = proj.list_chapters()
    if not chapters:
        console.print("[yellow]没有章节。[/yellow]")
        return
    last_no = max(int(c.stem) for c in chapters)
    end = end or last_no
    table = Table(title="全项目审计")
    table.add_column("章节")
    table.add_column("字数")
    table.add_column("状态")
    table.add_column("AI 味")
    table.add_column("雷达")
    for n in range(start, end + 1):
        target = proj.chapters_dir / ("%04d.md" % n)
        if not target.exists():
            table.add_row(str(n), "-", "[red]缺失[/red]", "-", "-")
            continue
        text = target.read_text(encoding="utf-8")
        wc = S.chapter_word_count(text)
        status = "[green]正常[/green]"
        if wc < 100:
            status = "[red]异常[/red]"
        elif "<think>" in text or " 区块" in text:
            status = "[red]有残片[/red]"
        detect_path = proj.novel_dir / "reports" / ("detect_%04d.md" % n)
        ai_score = "-"
        if detect_path.exists():
            d = detect_path.read_text(encoding="utf-8")
            m = re.search(r"AI 味指数[：:]?\s*(\d+)", d)
            if m:
                ai_score = m.group(1)
        radar_path = proj.novel_dir / "reports" / ("style_radar_%04d.md" % n)
        radar_score = "-"
        if radar_path.exists():
            r = radar_path.read_text(encoding="utf-8")
            m = re.search(r"总相似度[：:]?\s*(\d+)", r)
            if m:
                radar_score = m.group(1)
        table.add_row(str(n), str(wc), status, ai_score, radar_score)
    console.print(table)
    console.print("\n[dim]提示：novel batch detect / radar 可批量生成缺失的报告[/dim]")


def progress():
    """长篇写作进度统计：字数、章节数、卷进度、估计完成时间。"""
    proj = S.load_project()
    chapters = proj.list_chapters()
    total_chapters = 0
    if proj.outline_path.exists():
        outline_text = proj.outline_path.read_text(encoding="utf-8")
        total_chapters = len(re.findall(r"\*\*第[一二三四五六七八九十百千零0-9]+章", outline_text))
    target_words = proj.meta.get("target_words", 0)
    written_words = sum(S.chapter_word_count(c.read_text(encoding="utf-8")) for c in chapters)
    done_chapters = len(chapters)
    if total_chapters == 0:
        total_chapters = max(1, done_chapters)
    pct = 100.0 * done_chapters / total_chapters
    table = Table(title="长篇写作进度")
    table.add_column("指标")
    table.add_column("值")
    table.add_row("目标总字数", str(target_words or "未设置"))
    table.add_row("已写章节", str(done_chapters) + " / " + str(total_chapters) + " (%.1f%%)" % pct)
    table.add_row("已写字数", str(written_words))
    if target_words:
        wc_pct = 100.0 * written_words / target_words
        table.add_row("字数进度", "%.1f%%" % wc_pct)
    volumes_text = proj.volumes_path.read_text(encoding="utf-8") if proj.volumes_path.exists() else ""
    current_vol = "-"
    vol_progress = "-"
    vol_lines = re.findall(r"##\s*第([一二三四五六七八九十百千零0-9]+)卷[：:]?([^\n]*)", volumes_text)
    chap_to_vol = []
    chap_pat = re.compile(r"第\s*(\d+)\s*章?\s*[-到—]\s*第?\s*(\d+)\s*章")
    for vol_no, vol_title in vol_lines:
        idx = volumes_text.find("## 第" + vol_no + "卷")
        if idx < 0:
            continue
        seg = volumes_text[idx:idx + 500]
        m = chap_pat.search(seg)
        if m:
            chap_to_vol.append((vol_no, vol_title.strip(), int(m.group(1)), int(m.group(2))))
    for vol_no, vol_title, start, end in chap_to_vol:
        if start <= done_chapters <= end:
            current_vol = "第" + vol_no + "卷 " + vol_title
            vol_pct = 100.0 * (done_chapters - start + 1) / (end - start + 1)
            vol_progress = str(start) + "-" + str(end) + " 章: %.0f%%" % vol_pct
            break
    table.add_row("当前卷", current_vol)
    table.add_row("卷内进度", vol_progress)
    if done_chapters > 1:
        first = chapters[0].stat().st_mtime
        last = chapters[-1].stat().st_mtime
        span_min = (last - first) / 60
        if span_min > 0:
            avg = span_min / max(1, done_chapters - 1)
            remaining = total_chapters - done_chapters
            est_min = avg * remaining
            table.add_row("平均每章耗时", "%.1f 分钟" % avg)
            table.add_row("预计剩余", "%.0f 分钟（约 %.1f 小时）" % (est_min, est_min / 60))
    console.print(table)


def history():
    """查看所有章节的版本历史与字数变化。"""
    proj = S.load_project()
    if not proj.history_dir.exists():
        console.print("[yellow]暂无历史。[/yellow]")
        return
    files = sorted(proj.history_dir.glob("chapter_*.md"))
    table = Table(title="写作历史")
    table.add_column("章号")
    table.add_column("版本")
    table.add_column("字数")
    table.add_column("时间")
    for f in files:
        name = f.stem
        parts = name.split("_")
        chapter = parts[1] if len(parts) > 1 else "?"
        ver = parts[2] if len(parts) > 2 else "?"
        try:
            text = f.read_text(encoding="utf-8")
            wc = S.chapter_word_count(text)
        except Exception:
            wc = 0
        mtime = f.stat().st_mtime
        mtime_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
        table.add_row(chapter, ver, str(wc), mtime_str)
    console.print(table)


def register(app: typer.Typer) -> None:
    """注册所有项目查询与状态展示命令。"""
    app.command(name="list")(list_cmd)
    app.command()(info)
    app.command()(whereami)
    app.command()(status)
    app.command()(audit)
    app.command()(progress)
    app.command()(history)
