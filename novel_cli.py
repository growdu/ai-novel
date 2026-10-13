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
    style: str = typer.Option("", "--style", "-s", help="文风：可写预设名如'搞笑' / '冷峻' / '诗意'，或自由描述"),
    words: int = typer.Option(30000, "--words", "-w"),
    genre: str = typer.Option("现实 / 严肃文学", "--genre", "-g", help="题材：玄幻/仙侠/科幻/悬疑/推理/言情/历史/武侠/都市/校园/现实/严肃文学"),
    here: bool = typer.Option(False, "--here"),
):
    """初始化一个新的小说项目。"""
    from novel.prompts import list_genres, list_styles, get_genre_block, get_style_block
    if genre in ("现实", "严肃文学"):
        genre = "现实 / 严肃文学"
    style_block = get_style_block(style) if style else ""
    style_hint = style if (style and not style_block) else ""
    target = Path.cwd() if here else Path.cwd() / name
    if target.exists() and not here and any(target.iterdir()):
        console.print("[red]目录 %s 不为空，请换名字或加 --here。[/red]" % target)
        raise typer.Exit(1)
    target.mkdir(parents=True, exist_ok=True)
    meta = {"genre": genre, "target_words": words, "style_preset": style if (style and style_block) else ""}
    proj = S.init_project(target, title or name, theme=theme, meta=meta)
    style_content = "# 文风\n\n"
    if style_block:
        style_content += style_block + "\n\n"
    if style_hint:
        style_content += "## 自由文风描述\n\n" + style_hint + "\n"
    if style_block or style_hint:
        proj.style_path.write_text(style_content, encoding="utf-8")
    else:
        proj.style_path.write_text("# 文风\n\n（待填写）\n", encoding="utf-8")
    proj.characters_path.write_text("# 人物志\n\n（待生成）\n", encoding="utf-8")
    if genre:
        g_file = proj.novel_dir / "genre_preset.md"
        g_block = get_genre_block(genre)
        g_file.write_text("# 当前题材: " + genre + "\n\n" + g_block + "\n", encoding="utf-8")
    console.print(Panel.fit("[green]已创建项目:[/green] %s\n[green]标题:[/green] %s\n[green]题材:[/green] %s\n[green]文风:[/green] %s" % (proj.root, proj.title, genre, style or "（默认）"), title="novel init"))

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

@app.command()
def sprint(
    until: int = typer.Option(None, "--until", "-u", help="写到第几章"),
    count: int = typer.Option(None, "--count", "-c", help="写几章"),
    words: int = typer.Option(None, "--words", "-w"),
    iters: int = typer.Option(1, "--iters", "-i"),
    no_polish: bool = typer.Option(False, "--no-polish"),
):
    """自动冲刺：从最后一章后面继续写若干章。"""
    proj = S.load_project()
    cfg = load_global()
    chapters = proj.list_chapters()
    last_no = 0
    for c in chapters:
        try:
            n = int(c.stem)
            if n > last_no:
                last_no = n
        except ValueError:
            continue
    start = last_no + 1
    if until is not None:
        end = until
    elif count is not None:
        end = start + count - 1
    else:
        console.print("[yellow]请指定 --until N 或 --count N。[/yellow]")
        raise typer.Exit(1)
    if end < start:
        console.print("[yellow]没有需要写的章节（已经写到第 %d 章）。[/yellow]" % last_no)
        return
    console.print("[bold]冲刺：第 %d 章 -> 第 %d 章（%d 章）[/bold]" % (start, end, end - start + 1))
    write(start=start, end=end, words=words, iters=iters, no_polish=no_polish)

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
    genre = proj.meta.get("genre", "")
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

@app.command()
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

@app.command(name="continue")
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

@app.command()
def plan(no: int = typer.Argument(..., help="章节号")):
    """细化某章的章节大纲。"""
    proj = S.load_project()
    cfg = load_global()
    res = G.generate_chapter_plan(proj, no, client=LLMClient(cfg))
    console.print(Panel(res, title="第 %d 章细化大纲" % no))
    console.print("[green]已保存到[/green] " + str(proj.novel_dir / "chapter_plans" / ("%04d.md" % no)))

@app.command()
def doctor():
    """自动诊断项目状态：检查必要文件、配置、潜在问题。"""
    proj = S.load_project()
    cfg = load_global()
    issues = []
    warnings = []
    ok = []
    if not cfg.api_key:
        issues.append("未设置 OPENAI_API_KEY")
    if cfg.target_chapter_words < 1000:
        warnings.append("目标章节字数偏少，建议 2500-5000")
    if cfg.temperature < 0.7:
        warnings.append("temperature 偏稳，可能缺少变化")
    if not proj.outline_path.exists() or proj.outline_path.stat().st_size < 100:
        issues.append("大纲未生成（运行 novel outline）")
    if not proj.characters_path.exists() or proj.characters_path.stat().st_size < 100:
        issues.append("人物志未生成（运行 novel characters）")
    if not proj.world_path.exists() or proj.world_path.stat().st_size < 100:
        warnings.append("世界观未生成（运行 novel world，可选）")
    if not proj.volumes_path.exists() or proj.volumes_path.stat().st_size < 100:
        warnings.append("分卷未生成（运行 novel volumes，可选）")
    if not proj.style_path.exists() or proj.style_path.stat().st_size < 100:
        warnings.append("文风未设置（运行 init 时加 --style 或编辑 style.md）")
    chapters = proj.list_chapters()
    if not chapters:
        warnings.append("还没有写任何章节（运行 novel chapter 1）")
    else:
        for c in chapters:
            text = c.read_text(encoding="utf-8") if c.exists() else ""
            wc = S.chapter_word_count(text)
            if wc < 100:
                issues.append("第 " + c.stem + " 章字数 " + str(wc) + " 异常（可能生成失败）")
    samples = list(proj.samples_dir.glob("*.md")) if proj.samples_dir.exists() else []
    samples = [s for s in samples if not s.name.startswith("_")]
    if not samples:
        warnings.append("samples/ 目录为空（放入作者手写片段可显著提升风格）")
    if chapters and len(chapters) >= 2:
        if proj.state_path.stat().st_size < 100:
            warnings.append("state.md 过小（应该 >= 100 字节）")
        if proj.foreshadowing_path.stat().st_size < 100:
            warnings.append("foreshadowing.md 过小")
    if not issues:
        ok.append("通过所有关键检查")
    table = Table(title="novel doctor 诊断报告")
    table.add_column("状态")
    table.add_column("条数")
    table.add_row("[red]问题[/red]", str(len(issues)))
    table.add_row("[yellow]警告[/yellow]", str(len(warnings)))
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

@app.command(name="progress")
def progress():
    """长篇写作进度统计：字数、章节数、卷进度、估计完成时间。"""
    proj = S.load_project()
    chapters = proj.list_chapters()
    total_chapters = 0
    if proj.outline_path.exists():
        import re
        outline_text = proj.outline_path.read_text(encoding="utf-8")
        # 匹配 '**第N章' 形式的章节规划
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
    import re
    vol_pattern = re.compile(r"##\s*(第[一二三四五六七八九十百千零0-9]+卷[：:]?[^\n]*?)\s+[^*]*?起止章节[：:]?\s*第\s*(\d+)\s*章?[-到]\s*第?\s*(\d+)\s*章", re.MULTILINE)
    if not vol_pattern.pattern:
        vol_pattern = re.compile(r"##\s*(第[一二三四五六七八九十百千零0-9]+卷[：:]?[^\n]+)", re.MULTILINE)
    current_vol = "-"
    vol_progress = "-"
    # 简单方法：按行找 "## 第N卷" 开头
    vol_lines = re.findall(r"##\s*第([一二三四五六七八九十百千零0-9]+)卷[：:]?([^\n]*)", volumes_text)
    chap_to_vol = []
    chap_pat = re.compile(r"第\s*(\d+)\s*章?\s*[-到—]\s*第?\s*(\d+)\s*章")
    for vol_no, vol_title in vol_lines:
        # 找紧接着的 "第X-Y章"
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

@app.command()
def prompt(
    name: str = typer.Argument(..., help="提示词名"),
    show: bool = typer.Option(False, "--show", "-s", help="打印内容"),
    edit: bool = typer.Option(False, "--edit", "-e", help="用 $EDITOR 编辑"),
    lines: int = typer.Option(20, "--lines", "-l", help="show 模式下打印多少行"),
    reset: bool = typer.Option(False, "--reset", help="恢复默认（删除项目副本）"),
):
    """查看/编辑当前提示词。每个项目的提示词独立存放在 .novel/prompts/。"""
    proj = S.load_project()
    from novel import prompts as P
    proj_prompts_dir = proj.novel_dir / "prompts"
    proj_prompts_dir.mkdir(parents=True, exist_ok=True)
    proj_copy = proj_prompts_dir / (name + ".md")
    default_path = P.PROMPTS_DIR / (name + ".md")
    if not default_path.exists():
        console.print("[red]提示词 %s.md 不存在。可用提示词：[/red]" % name)
        for f in sorted(P.PROMPTS_DIR.glob("*.md")):
            console.print("  - " + f.stem)
        raise typer.Exit(1)
    if reset:
        if proj_copy.exists():
            proj_copy.unlink()
        console.print("[green]已恢复默认（删除项目副本 %s）[/green]" % proj_copy)
        return
    if not proj_copy.exists():
        proj_copy.write_text(default_path.read_text(encoding="utf-8"), encoding="utf-8")
        console.print("[dim]已从默认复制到 %s[/dim]" % proj_copy)
    if show:
        text = proj_copy.read_text(encoding="utf-8")
        all_lines = text.splitlines()
        for i, line in enumerate(all_lines[:lines], 1):
            console.print("%4d  %s" % (i, line))
        if len(all_lines) > lines:
            console.print("...（共 %d 行）" % len(all_lines))
        return
    if edit:
        import os, subprocess
        editor = os.environ.get("EDITOR", "vi")
        console.print("用 $EDITOR=%s 编辑 %s" % (editor, proj_copy))
        subprocess.call([editor, str(proj_copy)])
        console.print("[green]已保存。[/green]")
        return
    console.print("[bold]项目副本[/bold] %s (%d 字节)" % (proj_copy, proj_copy.stat().st_size))
    console.print("[bold]默认路径[/bold] %s" % default_path)
    console.print("使用 --show 查看内容，--edit 编辑，--reset 恢复默认。")


@app.command()
def gaps():
    """列出所有未回收的伏笔，及其预计回收章节是否已过。"""
    import re as _re
    proj = S.load_project()
    text = proj.foreshadowing_path.read_text(encoding="utf-8") if proj.foreshadowing_path.exists() else ""
    if not text:
        console.print("[yellow]伏笔簿为空。[/yellow]")
        return
    chapters = proj.list_chapters()
    last_no = max(int(c.stem) for c in chapters) if chapters else 0
    # 匹配 [FN] 之后跨多行，包含"回收"和"第N章"
    pattern = _re.compile(r"\[F(\d+)\][\s\S]{0,200}?回收[：:]?[\s\S]{0,40}?第\s*(\d+)\s*章")
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
    open_pattern = _re.compile(r"\[F(\d+)\][^。\n]*?未回收", _re.MULTILINE)
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

@app.command()
def index():
    """列出所有章节的索引（章节号、标题、字数、状态）。"""
    proj = S.load_project()
    titles = S.load_titles(proj)
    chapters = proj.list_chapters()
    if not chapters:
        console.print("[yellow]暂无章节。[/yellow]")
        return
    table = Table(title="全书索引")
    table.add_column("章节")
    table.add_column("标题")
    table.add_column("字数")
    table.add_column("状态")
    total = 0
    for c in chapters:
        n = int(c.stem)
        text = c.read_text(encoding="utf-8")
        wc = S.chapter_word_count(text)
        total += wc
        title = titles.get("%04d" % n, "（无）")
        if wc < 100:
            status = "[red]异常[/red]"
        elif "<think>" in text or " 区块" in text:
            status = "[red]残片[/red]"
        else:
            status = "[green]正常[/green]"
        table.add_row(str(n), title, str(wc), status)
    table.add_row("", "[bold]总计[/bold]", "[bold]" + str(total) + "[/bold]", "")
    console.print(table)

@app.command(name="retry-stuck")
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

@app.command()
def export(
    fmt: str = typer.Option("md", "--format", "-f", help="md 或 txt"),
    output: str = typer.Option(None, "--output", "-o", help="输出路径"),
):
    """合并所有章节为单一文件（书稿）。"""
    proj = S.load_project()
    out = G.export_combined(proj, fmt=fmt, output_path=Path(output) if output else None)
    if out is None:
        console.print("[yellow]没有章节可导出。[/yellow]")
    else:
        size = out.stat().st_size
        console.print("[green]已导出[/green] " + str(out) + " (" + str(size) + " 字节)")

@app.command()
def audit(
    start: int = typer.Option(1, "--start", "-s", help="起始章节"),
    end: int = typer.Option(None, "--end", "-e", help="结束章节（默认最后一章）"),
):
    """对所有章节做综合审计：字数 + 异常 + AI 味 + 雷达。"""
    import re as _re
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
            m = _re.search(r"AI 味指数[：:]?\s*(\d+)", d)
            if m:
                ai_score = m.group(1)
        radar_path = proj.novel_dir / "reports" / ("style_radar_%04d.md" % n)
        radar_score = "-"
        if radar_path.exists():
            r = radar_path.read_text(encoding="utf-8")
            m = _re.search(r"总相似度[：:]?\s*(\d+)", r)
            if m:
                radar_score = m.group(1)
        table.add_row(str(n), str(wc), status, ai_score, radar_score)
    console.print(table)
    console.print("\n[dim]提示：novel batch detect / radar 可批量生成缺失的报告[/dim]")

@app.command()
def rollback(
    no: int = typer.Argument(..., help="章节号"),
    to_version: str = typer.Option(None, "--to", help="回滚到哪个版本"),
    list_only: bool = typer.Option(False, "--list", "-l", help="只列出历史版本"),
):
    """把当前章节回滚到指定历史版本（备份当前为新版本）。"""
    proj = S.load_project()
    if list_only:
        files = sorted(proj.history_dir.glob("chapter_%04d_v*.md" % no)) if proj.history_dir.exists() else []
        if not files:
            console.print("[yellow]无历史版本。[/yellow]")
            return
        console.print("[bold]第 " + str(no) + " 章历史版本[/bold]")
        for f in files:
            import time
            t = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))
            console.print("  " + f.stem + "  " + str(f.stat().st_size) + " 字节  " + t)
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
        S.save_chapter(proj, no, current, backup=True)
    target_text = target.read_text(encoding="utf-8")
    S.save_chapter(proj, no, target_text, backup=False)
    console.print("[green]已回滚第 " + str(no) + " 章到 " + to_version + "。回滚前内容已备份为新版本。[/green]" % (no, to_version))

@app.command()
def fix(
    no: int = typer.Argument(..., help="章节号"),
    dry: bool = typer.Option(True, "--dry/--no-dry", help="只检查不修复"),
):
    """检测并修复异常章节（0 字节 / 过短 / 残片）。"""
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
        console.print("[yellow]第 " + str(no) + " 章异常：[/yellow]")
        for i, s in enumerate(issues, 1):
            console.print("  " + str(i) + ". " + s)
        if not dry:
            console.print("\n[dim]建议：rm " + str(target) + " && novel chapter " + str(no) + " 重写[/dim]")
    else:
        console.print("[green]第 " + str(no) + " 章正常（" + str(wc) + " 字）。[/green]")

@app.command()
def batch(
    action: str = typer.Argument(..., help="批量动作: polish / detect / radar / title"),
    start: int = typer.Option(1, "--start", "-s", help="起始章节"),
    end: int = typer.Option(None, "--end", "-e", help="结束章节（默认最后一章）"),
    skip_empty: bool = typer.Option(True, "--skip-empty", help="跳过空章节"),
):
    """批量执行 polish / detect / radar / title。"""
    proj = S.load_project()
    cfg = load_global()
    client = LLMClient(cfg)
    chapters = proj.list_chapters()
    if not chapters:
        console.print("[yellow]没有章节。[/yellow]")
        return
    last_no = max(int(c.stem) for c in chapters)
    end = end or last_no
    console.print("[bold]批量 " + action + "：第 " + str(start) + "-" + str(end) + " 章[/bold]")
    for n in range(start, end + 1):
        target = proj.chapters_dir / ("%04d.md" % n)
        if not target.exists():
            console.print("  [dim]第 " + str(n) + " 章不存在，跳过[/dim]")
            continue
        text = target.read_text(encoding="utf-8")
        if skip_empty and S.chapter_word_count(text) < 100:
            console.print("  [dim]第 " + str(n) + " 章字数过少，跳过[/dim]")
            continue
        try:
            if action == "polish":
                outline_text = proj.outline_path.read_text(encoding="utf-8") if proj.outline_path.exists() else ""
                plan = G.parse_chapter_plan(outline_text, n)
                prev = S.load_chapter(proj, n - 1)
                prev_tail = prev[-500:] if prev else ""
                msgs = P.build_polish_messages(text, plan, prev_tail, "", "")
                res = client.chat_with_continuation(msgs, target_words=len(text) // 3, max_total_tokens=20000, temperature=0.9)
                new_text = (res.content or "").strip()
                S.save_chapter(proj, n, new_text)
                console.print("  [green]第 " + str(n) + " 章已润色[/green]")
            elif action == "detect":
                msgs = P.build_detect_messages(text)
                res = client.chat(msgs, temperature=0.3, max_tokens=2000)
                p = proj.novel_dir / "reports" / ("detect_%04d.md" % n)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(res.content, encoding="utf-8")
                console.print("  [green]第 " + str(n) + " 章已检测 -> " + p.name + "[/green]")
            elif action == "radar":
                G.style_radar(proj, n, client=client)
                console.print("  [green]第 " + str(n) + " 章已雷达[/green]")
            elif action == "title":
                G.generate_chapter_title(proj, n, client=client)
                console.print("  [green]第 " + str(n) + " 章已生成标题[/green]")
            else:
                console.print("[red]未知动作: " + action + "。可用: polish / detect / radar / title[/red]")
                raise typer.Exit(1)
        except Exception as e:
            console.print("  [red]第 " + str(n) + " 章失败: " + str(e) + "[/red]")
    console.print("[bold]批量 " + action + " 完成[/bold]")


@app.command()
def diff(
    no: int = typer.Argument(..., help="章节号"),
    ver_a: str = typer.Option(None, "--from", "-a", help="版本 A（章节号或版本号）"),
    ver_b: str = typer.Option(None, "--to", "-b", help="版本 B（章节号或版本号）"),
    stats_only: bool = typer.Option(False, "--stats", help="只显示统计"),
    context: int = typer.Option(3, "--context", "-c", help="显示多少行上下文"),
):
    """对比两版章节的差异。"""
    proj = S.load_project()
    # 默认: --from current --to 最近历史
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
        diff = unified_diff(a_text, b_text, a_name, b_name, n=context)
        if diff:
            console.print()
            for line in diff.splitlines()[:200]:
                console.print(line)
            if len(diff.splitlines()) > 200:
                console.print("\n[dim]... 以下省略（用 --context 调大）[/dim]")
        else:
            console.print("\n[green]两版本完全一致。[/green]")

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
            import re as _re
            pattern = _re.compile(r"^##\s+" + _re.escape(character) + "\s*$([\s\S]*?)(?=^##\s+|\Z)", _re.MULTILINE)
            m = pattern.search(text)
            if m:
                console.print(Panel(m.group(1).strip(), title=character + " 弧线"))
            else:
                console.print("[yellow]未找到人物 " + character + "[/yellow]")
        else:
            for line in text.splitlines():
                if character in line:
                    console.print(line, style="bold")
                else:
                    console.print(line)

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
