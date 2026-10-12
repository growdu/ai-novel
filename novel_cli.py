"""novel CLI 入口。"""
from __future__ import annotations
import os
import sys
from pathlib import Path
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from novel.config import GlobalConfig, load_global
from novel import storage as S
from novel import generator as G
from novel.llm import LLMClient
from novel import prompts as P
app = typer.Typer(help="AI 小说创作工具")
console = Console()
@app.callback()
def _main(ctx: typer.Context, verbose: bool = typer.Option(True, "--verbose/--quiet", "-v/-q")):
    ctx.obj = {"verbose": verbose}
def _print_cfg(cfg):
    t = Table(title="当前配置")
    t.add_column("项")
    t.add_column("值")
    for k, v in cfg.masked().items():
        t.add_row(k, str(v))
    console.print(t)
@app.command()
def config(
    show: bool = typer.Option(False, "--show"),
    set_base_url: str = typer.Option(None, "--base-url"),
    set_model: str = typer.Option(None, "--model"),
    set_key: str = typer.Option(None, "--api-key"),
    dry_run: bool = typer.Option(None, "--dry-run/--no-dry-run"),
):
    cfg = load_global()
    if set_base_url:
        os.environ["OPENAI_BASE_URL"] = set_base_url
        cfg.base_url = set_base_url
    if set_model:
        os.environ["OPENAI_MODEL"] = set_model
        cfg.model = set_model
    if set_key:
        os.environ["OPENAI_API_KEY"] = set_key
        cfg.api_key = set_key
    if dry_run is not None:
        os.environ["DRY_RUN"] = "true" if dry_run else "false"
        cfg.dry_run = dry_run
    _print_cfg(cfg)

@app.command()
def init(
    name: str = typer.Argument(..., help="小说项目目录名"),
    title: str = typer.Option(None, "--title", "-t"),
    theme: str = typer.Option("", "--theme"),
    style: str = typer.Option("", "--style"),
    words: int = typer.Option(30000, "--words", "-w"),
    genre: str = typer.Option("现实", "--genre", "-g"),
    here: bool = typer.Option(False, "--here"),
):
    """初始化一个新的小说项目。"""
    target = Path.cwd() if here else Path.cwd() / name
    if target.exists() and not here and any(target.iterdir()):
        console.print("[red]目录 %s 不为空，请换名字或加 --here。[/red]" % target)
        raise typer.Exit(1)
    target.mkdir(parents=True, exist_ok=True)
    proj = S.init_project(target, title or name, theme=theme, meta={"genre": genre, "target_words": words})
    if style:
        proj.style_path.write_text("# 文风\n\n" + style + "\n", encoding="utf-8")
    else:
        proj.style_path.write_text("# 文风\n\n（待填写，可写：致敬某某、目标读者、参考作家）\n", encoding="utf-8")
    proj.characters_path.write_text("# 人物志\n\n（待生成）\n", encoding="utf-8")
    console.print(Panel.fit("[green]已创建项目:[/green] %s\n[green]标题:[/green] %s\n[green]主题:[/green] %s" % (proj.root, proj.title, theme or "（未填）"), title="novel init"))

@app.command()
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

@app.command(name="characters")
def characters_cmd(
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

@app.command()
def chapter(
    no: int = typer.Argument(..., help="章节号，从 1 开始"),
    words: int = typer.Option(None, "--words", "-w"),
    iters: int = typer.Option(2, "--iters", "-i"),
    no_polish: bool = typer.Option(False, "--no-polish"),
    extra: str = typer.Option("", "--extra", "-e"),
):
    """生成指定的一章。"""
    proj = S.load_project()
    cfg = load_global()
    outline_text = proj.outline_path.read_text(encoding="utf-8") if proj.outline_path.exists() else ""
    characters_text = proj.characters_path.read_text(encoding="utf-8") if proj.characters_path.exists() else ""
    style = proj.style_path.read_text(encoding="utf-8") if proj.style_path.exists() else ""
    plan = G.parse_chapter_plan(outline_text, no)
    prev = S.load_chapter(proj, no - 1)
    prev_tail = prev[-500:] if prev else ""
    ctx = {
        "title": proj.title,
        "outline": outline_text,
        "characters": characters_text,
        "style": style,
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

@app.command()
def write(
    start: int = typer.Option(1, "--start", "-s"),
    end: int = typer.Option(1, "--end", "-e"),
    words: int = typer.Option(None, "--words", "-w"),
    iters: int = typer.Option(1, "--iters", "-i"),
    no_polish: bool = typer.Option(False, "--no-polish"),
):
    """一次性写多章。"""
    proj = S.load_project()
    cfg = load_global()
    outline_text = proj.outline_path.read_text(encoding="utf-8") if proj.outline_path.exists() else ""
    characters_text = proj.characters_path.read_text(encoding="utf-8") if proj.characters_path.exists() else ""
    style = proj.style_path.read_text(encoding="utf-8") if proj.style_path.exists() else ""
    client = LLMClient(cfg)
    for n in range(start, end + 1):
        plan = G.parse_chapter_plan(outline_text, n)
        prev = S.load_chapter(proj, n - 1)
        prev_tail = prev[-500:] if prev else ""
        ctx = {
            "title": proj.title,
            "outline": outline_text,
            "characters": characters_text,
            "style": style,
            "chapter_plan": plan,
            "prev_chapter_tail": prev_tail,
            "state": proj.state_path.read_text(encoding="utf-8") if proj.state_path.exists() else "",
            "foreshadow": proj.foreshadowing_path.read_text(encoding="utf-8") if proj.foreshadowing_path.exists() else "",
            "world": proj.world_path.read_text(encoding="utf-8") if proj.world_path.exists() else "",
            "timeline": proj.timeline_path.read_text(encoding="utf-8") if proj.timeline_path.exists() else "",
            "volumes": proj.volumes_path.read_text(encoding="utf-8") if proj.volumes_path.exists() else "",
            "arc": (proj.arcs_dir / "_overview.md").read_text(encoding="utf-8") if (proj.arcs_dir / "_overview.md").exists() else "",
        }
        req = G.ChapterRequest(chapter_no=n, target_words=words or cfg.target_chapter_words)
        console.print("\n[bold]=== 第 %d 章 ===[/bold]" % n)
        res = G.write_chapter_extended(req, ctx, project=proj, client=client, max_iters=iters, update_after=True, verbose=True, do_polish=not no_polish)
        S.save_chapter(proj, n, res.content)
        console.print("[green]已保存[/green] %s | 字数 %d | 迭代 %d 轮" % (proj.chapters_dir / ("%04d.md" % n), res.word_count, res.iterations))

@app.command()
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
    S.save_chapter(proj, no, res.content)
    console.print("[green]已润色并覆盖第 %d 章。原版本已备份到 history/。[/green]" % no)

@app.command()
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

@app.command(name="world")
def world_cmd():
    """生成世界观设定（基于大纲与主题）。"""
    proj = S.load_project()
    cfg = load_global()
    theme = proj.meta.get("theme", "")
    genre = proj.meta.get("genre", "现实")
    G.generate_world(proj, theme, genre, client=LLMClient(cfg))
    console.print("[green]已保存[/green] " + str(proj.world_path))

@app.command(name="volumes")
def volumes_cmd():
    """分卷（长篇分多卷）。"""
    proj = S.load_project()
    cfg = load_global()
    G.generate_volumes(proj, client=LLMClient(cfg))
    console.print("[green]已保存[/green] " + str(proj.volumes_path))

@app.command()
def timeline():
    """基于大纲+已写章节，维护故事内时间线。"""
    proj = S.load_project()
    cfg = load_global()
    G.generate_timeline(proj, client=LLMClient(cfg))
    console.print("[green]已保存[/green] " + str(proj.timeline_path))

@app.command()
def volume_report(volume: int = typer.Option(1, "--volume", "-v", help="第几卷")):
    """生成指定卷的卷末报告。"""
    proj = S.load_project()
    cfg = load_global()
    G.generate_volume_report(proj, client=LLMClient(cfg), volume_no=volume)
    console.print("[green]已保存[/green] " + str(proj.novel_dir / "reports" / ("volume_%02d_report.md" % volume)))

@app.command(name="expand-scene")
def expand_scene_cmd(
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

@app.command()
def radar(no: int = typer.Argument(..., help="章节号")):
    """风格雷达：量化某章与 samples 的风格相似度。"""
    proj = S.load_project()
    cfg = load_global()
    res = G.style_radar(proj, no, client=LLMClient(cfg))
    if res:
        console.print(Panel(res, title="第 %d 章风格雷达" % no))
    else:
        console.print("[red]第 %d 章不存在。[/red]" % no)

@app.command()
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
        import time
        mtime_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
        table.add_row(chapter, ver, str(wc), mtime_str)
    console.print(table)

@app.command()
def title(no: int = typer.Argument(..., help="章节号"), force: bool = typer.Option(False, "--force", help="重新生成")):
    """为指定章节生成标题。"""
    proj = S.load_project()
    cfg = load_global()
    t = G.generate_chapter_title(proj, no, client=LLMClient(cfg), force=force)
    if t:
        console.print("[green]第 %d 章标题:[/green] %s" % (no, t))
    else:
        console.print("[red]第 %d 章不存在。[/red]" % no)

@app.command()
def rolling():
    """手动刷新全书滚动摘要。"""
    proj = S.load_project()
    cfg = load_global()
    G.update_rolling_summary(proj, client=LLMClient(cfg))
    console.print("[green]已保存[/green] " + str(proj.rolling_summary_path))

@app.command()
def check(lookback: int = typer.Option(10, "--lookback", "-k")):
    """跨章节一致性检查。"""
    proj = S.load_project()
    cfg = load_global()
    G.check_consistency(proj, client=LLMClient(cfg), lookback=lookback)
    console.print("[green]已保存[/green] " + str(proj.novel_dir / "consistency_report.md"))

@app.command()
def state():
    """手动刷新故事状态摘要（每章写完会自动更新）。"""
    proj = S.load_project()
    cfg = load_global()
    G.update_state(proj, client=LLMClient(cfg))
    console.print("[green]已保存[/green] " + str(proj.state_path))

@app.command()
def arc():
    """刷新人物弧线总览。"""
    proj = S.load_project()
    cfg = load_global()
    G.update_arc(proj, client=LLMClient(cfg))
    console.print("[green]已保存[/green] " + str(proj.arcs_dir / "_overview.md"))

@app.command()
def foreshadow():
    """刷新伏笔簿。"""
    proj = S.load_project()
    cfg = load_global()
    G.update_foreshadow(proj, client=LLMClient(cfg))
    console.print("[green]已保存[/green] " + str(proj.foreshadowing_path))

@app.command()
def status():
    """查看当前项目的状态。"""
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

if __name__ == "__main__":
    app()
