"""novel CLI 入口。"""
from __future__ import annotations
import os
import sys
from pathlib import Path
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from novel import __version__
from novel.config import load_global
from novel import storage as S
from novel import generator as G
from novel.llm import LLMClient
from novel import prompts as P
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
    if version:
        console.print(f"[bold]novel-writer[/bold] {__version__}")
        raise typer.Exit()
    ctx.obj = {"verbose": verbose}


def _load_project():
    """友好的项目加载：找不到时给出操作建议。"""
    try:
        return S.load_project()
    except S.ProjectNotFoundError as e:
        console.print(Panel.fit(
            str(e),
            title="[red]未找到 .novel 项目目录[/red]",
            border_style="red",
        ))
        raise typer.Exit(1) from None
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
def version(
    short: bool = typer.Option(False, "--short", "-s", help="只输出版本号，无颜色"),
):
    """显示 novel-writer 版本号与运行环境。"""
    py = sys.version.split()[0]
    if short:
        typer.echo(__version__)
        raise typer.Exit()
    table = Table(title="novel-writer 环境信息", show_header=False)
    table.add_column("项", style="cyan")
    table.add_column("值")
    table.add_row("novel-writer", __version__)
    table.add_row("Python", py)
    table.add_row("平台", sys.platform)
    table.add_row("typer", typer.__version__ if hasattr(typer, "__version__") else "unknown")
    table.add_row("模型", load_global().model)
    table.add_row("base_url", load_global().base_url)
    console.print(table)


@app.command()
def setup(
    force: bool = typer.Option(False, "--force", "-f", help="已存在 .env 时仍覆盖"),
    non_interactive: bool = typer.Option(False, "--no-input", help="用环境变量 / 已有 .env，非交互"),
):
    """首次配置向导：交互式生成 .env。

    依次询问 API base URL、API key、模型、温度、章节字数、DRY_RUN。
    已存在 .env 时默认跳过；--force 覆盖。
    """
    env_path = Path.cwd() / ".env"
    if env_path.exists() and not force:
        console.print(f"[yellow].env 已存在：[/yellow] {env_path}\n[dim]用 --force 覆盖，或直接编辑。[/dim]")
        if non_interactive:
            return
        if not Confirm.ask("是否覆盖现有 .env？", default=False):
            return
    if non_interactive:
        cfg = load_global()
        lines = [
            f"OPENAI_BASE_URL={cfg.base_url}",
            f"OPENAI_API_KEY={cfg.api_key or ''}",
            f"OPENAI_MODEL={cfg.model}",
            f"TEMPERATURE={cfg.temperature}",
            f"TOP_P={cfg.top_p}",
            f"MAX_TOKENS={cfg.max_tokens}",
            f"TARGET_CHAPTER_WORDS={cfg.target_chapter_words}",
            f"DRY_RUN={'true' if cfg.dry_run else 'false'}",
        ]
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        console.print(f"[green]已写入：[/green] {env_path}")
        return
    console.print(Panel.fit(
        "[bold]novel-writer 首次配置向导[/bold]\n\n"
        "下面会询问：API 地址、API key、模型、温度、DRY_RUN。\n"
        "所有问题都可以直接回车用默认值。\n"
        "完成后会在当前目录生成 .env 文件。",
        title="setup",
    ))
    base_url = Prompt.ask("API base URL", default="https://api.minimaxi.com/v1")
    api_key = Prompt.ask("API key", password=True, default=load_global().api_key or "")
    model = Prompt.ask("模型", default="minimax-Text-01")
    temperature = float(Prompt.ask("temperature（0.7 稳 / 0.95 放飞）", default="0.9"))
    chapter_words = int(Prompt.ask("目标章节字数", default="3000"))
    dry_run = Confirm.ask("开启 DRY_RUN 模式（不真调用 API）？", default=False)
    lines = [
        "# novel-writer 配置（由 setup 命令生成，可手动修改）",
        f"OPENAI_BASE_URL={base_url}",
        f"OPENAI_API_KEY={api_key}",
        f"OPENAI_MODEL={model}",
        f"TEMPERATURE={temperature}",
        "TOP_P=0.95",
        "MAX_TOKENS=4096",
        f"TARGET_CHAPTER_WORDS={chapter_words}",
        f"DRY_RUN={'true' if dry_run else 'false'}",
        "",
    ]
    env_path.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"\n[green]✓ 已写入：[/green] {env_path}")
    console.print("\n[dim]下一步：[/dim]")
    console.print("  1. novel doctor      # 验证配置")
    console.print("  2. novel init my_novel --title '你的小说标题' --genre 悬疑 --style 冷峻")
    console.print("  3. cd my_novel && novel outline && novel characters && novel chapter 1")


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
    from novel.prompts import get_genre_block, get_style_block
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

@app.command()
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
    """基于源小说（高热度小说）改编成新小说。"""
    proj = S.load_project()
    cfg = load_global()
    client = LLMClient(cfg)
    src = source_text
    if source_file:
        from pathlib import Path as _P
        p = _P(source_file)
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
        full_text = "# 源小说骨架\n\n" + skeleton_text + "\n\n---\n\n" + "# 改编方案\n\n" + adapt_text
    else:
        full_text = adapt_text
    if save:
        out = proj.novel_dir / "adapt.md"
        out.write_text(full_text, encoding="utf-8")
        # 顺手把 title / genre / style 写入 project meta
        if title:
            proj.meta["title"] = title
        proj.meta["genre"] = target_genre
        proj.meta["style_preset"] = target_style
        proj.meta["source"] = source_file or "（用户输入）"
        from novel.storage import _write_yaml
        _write_yaml(proj.project_yaml, proj.meta)
        console.print("[green]已保存改编方案:[/green] " + str(out))
        console.print("\n[dim]下一步建议：[/dim]")
        console.print("  1. novel outline 用改编方案生成完整大纲")
        console.print("  2. novel characters 生成新人物志")
        console.print("  3. novel chapter 1 开始写")
    else:
        console.print(Panel(full_text, title="改编方案"))

@app.command()
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
        from pathlib import Path as _P
        p = _P(source_file)
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

@app.command()
def genres():
    """列出所有支持的题材（严肃向）。"""
    from novel.prompts import list_genres
    console.print("[bold]支持的题材（严肃向，10 个）[/bold]")
    for g in list_genres():
        console.print("  - " + g)

@app.command(name="webnovel-pack")
def webnovel_pack(
    name: str = typer.Argument(..., help="项目目录名"),
    title: str = typer.Option(..., "--title", "-t", help="小说标题"),
    theme: str = typer.Option(..., "--theme", help="一句话主题"),
    sub_genre: str = typer.Option("修仙 / 玄幻（网文风）", "--genre", "-g", help="网文子题材（用 webnovel-genres 查看）"),
    sub_style: str = typer.Option("经典爽文", "--style", "-y", help="爽感文风（用 webnovel-styles 查看）"),
    words: int = typer.Option(2000000, "--words", "-w"),
    idea: str = typer.Option("", "--idea", help="金手指 / 核心设定（可选）"),
):
    """一键网文包：建项目 + 选网文题材 + 选爽文文风 + 写金手指。"""
    from novel.prompts import get_webnovel_genre_block, get_webnovel_style_block
    genre_block = get_webnovel_genre_block(sub_genre)
    style_block = get_webnovel_style_block(sub_style)
    if not genre_block:
        console.print("[red]未知网文题材 %s。[/red]" % sub_genre)
        raise typer.Exit(1)
    if not style_block:
        console.print("[red]未知爽感文风 %s。[/red]" % sub_style)
        raise typer.Exit(1)
    target = Path.cwd() / name
    if target.exists() and any(target.iterdir()):
        console.print("[red]目录 %s 不为空。[/red]" % target)
        raise typer.Exit(1)
    target.mkdir(parents=True, exist_ok=True)
    S.init_project(target, title, theme=theme, meta={"genre": sub_genre, "target_words": words, "style_preset": sub_style, "kind": "webnovel"})
    style_content = "# 网文爽感文风\n\n" + style_block + "\n\n## 核心金手指\n\n" + (idea or "（待定）") + "\n"
    (target / ".novel" / "style.md").write_text(style_content, encoding="utf-8")
    (target / ".novel" / "genre_preset.md").write_text("# 网文题材: " + sub_genre + "\n\n" + genre_block + "\n", encoding="utf-8")
    plan_text = "## 核心设定\n\n" + (idea or "（待补充）") + "\n\n## 黄金三章骨架\n\n1. 第 1 章 - 困境：主角被压迫\n2. 第 2 章 - 觉醒：金手指出现\n3. 第 3 章 - 打脸：第一次装逼打脸\n\n## 后续节奏建议\n\n- 每 10-20 章一个升级小高潮\n- 每 30-50 章一个地图跃迁\n- 每 100 章一个 boss 战\n\n## 写作时清单\n\n- [ ] 第 1 章必须有清晰困境\n- [ ] 第 2 章金手指规则明确\n- [ ] 第 3 章打脸让读者爽到\n- [ ] 主角性格不能完美\n- [ ] 每章结尾留钩子\n"
    (target / ".novel" / "webnovel_plan.md").write_text(plan_text, encoding="utf-8")
    console.print(Panel.fit("[green]网文项目已建:[/green] " + str(target) + "\n[green]标题:[/green] " + title + "\n[green]题材:[/green] " + sub_genre + "\n[green]文风:[/green] " + sub_style, title="novel webnovel-pack"))
    console.print("\n[dim]下一步：[/dim]")
    console.print("  1. cd " + str(target))
    console.print("  2. novel outline")
    console.print("  3. novel characters")
    console.print("  4. novel chapter 1  # 黄金三章第 1 章：困境")
    console.print("  5. novel chapter 2  # 金手指觉醒")
    console.print("  6. novel chapter 3  # 首次打脸")

@app.command(name="webnovel-genres")
def webnovel_genres_cmd():
    """列出所有支持的网文题材（9 个）。"""
    from novel.prompts import list_webnovel_genres
    console.print("[bold]支持的网文题材（9 个）[/bold]")
    for g in list_webnovel_genres():
        console.print("  - " + g)

@app.command(name="webnovel-styles")
def webnovel_styles_cmd():
    """列出所有支持的网文爽感文风（10 个）。"""
    from novel.prompts import list_webnovel_styles
    console.print("[bold]支持的网文爽感文风（10 个）[/bold]")
    for s in list_webnovel_styles():
        console.print("  - " + s)

@app.command(name="styles")
def styles_cmd():
    """列出所有支持的文风。"""
    from novel.prompts import list_styles
    console.print("[bold]支持的文风[/bold]（11 个）")
    for s in list_styles():
        console.print("  - " + s)

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

@app.command()
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


@app.command(name="list")
def list_cmd(
    path: str = typer.Option(".", "--path", "-p", help="搜索起点目录"),
    depth: int = typer.Option(3, "--depth", "-d", help="最多向下搜索几层"),
):
    """列出指定目录（含子目录）下所有 novel 项目。

    用于管理多个项目时快速找到它们，不用一个个 cd。
    """
    base = Path(path).resolve()
    if not base.exists():
        console.print(f"[red]目录不存在：[/red] {base}")
        raise typer.Exit(1)
    projects = set()
    # 限制搜索深度，避免扫描到无关目录
    if depth < 1:
        depth = 1
    # 用 rglob 然后过滤深度
    for novel_dir in base.glob("**/.novel"):
        rel = novel_dir.relative_to(base)
        # 深度 = rel.parts 中非 .novel 之前的层数
        parts = [p for p in rel.parts if p != ".novel"]
        if len(parts) > depth:
            continue
        # 跳过隐藏目录（如 .venv/.git/.cache 等）下的项目
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


@app.command()
def info(
    name: str = typer.Argument(..., help="项目目录名（相对于当前目录或绝对路径）"),
):
    """查看指定项目的元信息，不需要 cd 进项目。

    比 status 更"远观"，适合快速了解项目配置。
    """
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


@app.command()
def whereami():
    """显示当前所在的项目路径与元信息（不要求在项目里）。

    在项目里 → 显示项目名 + 路径。
    不在项目里 → 给"不是错误"，用 yellow 提示，给出解决建议。
    """
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


@app.command()
def auto(
    name: str = typer.Argument(None, help="项目目录名（与 --here 互斥）"),
    title: str = typer.Option(..., "--title", "-t", help="小说标题（必填）"),
    theme: str = typer.Option("", "--theme", help="一句话主题"),
    genre: str = typer.Option("现实 / 严肃文学", "--genre", "-g", help="题材"),
    style: str = typer.Option("", "--style", "-s", help="文风（预设名或自由描述）"),
    words: int = typer.Option(30000, "--words", "-w", help="目标总字数"),
    chapters: int = typer.Option(None, "--chapters", help="显式指定章节数"),
    quality: str = typer.Option("standard", "--quality", help="质量档：draft / standard / premium"),
    budget: float = typer.Option(0.0, "--budget", help="成本上限 CNY；0=不限"),
    resume: bool = typer.Option(False, "--resume", help="强制续跑"),
    fresh: bool = typer.Option(False, "--fresh", help="强制从头跑（覆盖旧进度）"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    here: bool = False,
    force: bool = False,
):
    """一键全自动写小说：给定最小信息，自动跑完规划→写作→润色→一致性→导出。

    自动可恢复：每章写完即保存到 .novel/auto_state.json，Ctrl-C 后下次
    novel auto 自动从中断处续跑（无需 --resume）。

    Examples:
        novel auto demo --title "冬夜的灰" --theme "1995 东北命案" \\
            --genre 悬疑 --style 冷峻 --words 60000 --quality premium
    """
    from novel.auto import AutoSpec, run_auto_novel
    from novel.auto_state import AutoSpec as _SpecAlias, AutoState as _StateAlias

    # 解析 quality
    from novel.auto_state import QualityPreset
    try:
        quality_preset = QualityPreset(quality)
    except ValueError:
        console.print(f"[red]未知 quality：{quality}。可选：draft/standard/premium[/red]")
        raise typer.Exit(1)

    cfg = load_global()
    is_dry = dry_run or cfg.dry_run

    # 项目目录
    if here:
        project_dir = Path.cwd()
    elif name:
        project_dir = Path.cwd() / name
    else:
        console.print("[red]请提供 NAME 或加 --here。[/red]")
        raise typer.Exit(1)

    # 项目 init / load
    proj = None
    try:
        proj = S.load_project(project_dir)
        if not here and name and not force:
            # 已存在的项目目录，继续续跑
            pass
    except S.ProjectNotFoundError:
        if here and not force:
            if not Confirm.ask(f"在 {project_dir} 创建新项目？", default=True):
                raise typer.Exit()
        project_dir.mkdir(parents=True, exist_ok=True)
        proj = S.init_project(
            project_dir,
            title,
            theme=theme,
            meta={"genre": genre, "target_words": words, "style_preset": style},
        )

    if proj is None:
        console.print("[red]无法初始化或加载项目。[/red]")
        raise typer.Exit(1)

    # 续跑检测
    state_path = proj.root / ".novel" / "auto_state.json"
    effective_resume = True
    if state_path.exists() and not fresh:
        from novel.auto_state import AutoState
        st = AutoState.load(proj.root)
        if st and st.spec.get("title") == title:
            done = sum(1 for r in st.chapter_results.values() if r.status in ("generated", "polished"))
            console.print(Panel.fit(
                f"[green]检测到上次进度[/green]\n"
                f"阶段: {st.phase.value} | 已完成: {done}/{st.chapters_total}\n"
                f"已用 token: {st.cumulative_tokens:,} | 用时: {(st.updated_at - st.started_at)/60:.0f} 分钟\n\n"
                f"[dim]直接 Enter 续跑；输入 n 重新开始[/dim]",
                title="novel auto 续跑",
            ))
            if not resume:
                ans = Prompt.ask("续跑？", default="y")
                if ans.lower().startswith("n"):
                    effective_resume = False
        else:
            effective_resume = False
    else:
        effective_resume = False

    # 构造 spec
    spec = AutoSpec(
        title=title,
        theme=theme or "",
        genre=genre,
        style=style,
        target_words=words,
        target_chapters=chapters or 0,
        quality=quality_preset,
    )

    # 启动编排器
    try:
        out = run_auto_novel(
            spec, proj.root, cfg=cfg,
            resume=effective_resume, budget_cny=budget,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断。再次运行 novel auto 自动续跑。[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(f"[red]novel auto 失败：{e}[/red]")
        raise typer.Exit(1)
    console.print(Panel.fit(f"[green]✓ 全书完成：[/green] {out}", title="novel auto"))


@app.command()
def templates():
    """列出推荐的题材 + 文风组合，一键 init 用。

    比 webnovel-pack 更灵活，适合严肃向项目快速起步。
    """
    templates = [
        {"name": "东北悬疑", "genre": "悬疑", "style": "冷峻", "words": 80000, "desc": "致敬双雪涛 / 班宇的北方叙事"},
        {"name": "硬科幻", "genre": "科幻", "style": "朴素", "words": 60000, "desc": "贴近刘慈欣 / 阿西莫夫的扎实感"},
        {"name": "古典言情", "genre": "言情", "style": "诗意", "words": 50000, "desc": "致敬张爱玲 / 王安忆的细腻"},
        {"name": "武侠经典", "genre": "武侠", "style": "朴素", "words": 120000, "desc": "致敬金庸 / 古龙的江湖气"},
        {"name": "轻松校园", "genre": "校园", "style": "轻松", "words": 30000, "desc": "日系轻小说 / 国产青春剧"},
        {"name": "诗意现实", "genre": "现实", "style": "诗意", "words": 40000, "desc": "致敬汪曾祺 / 沈从文的淡墨"},
        {"name": "黑色幽默", "genre": "都市", "style": "黑色幽默", "words": 50000, "desc": "致敬余华 / 王小波的戏谑"},
        {"name": "网文经典", "genre": "修仙", "style": "经典爽文", "words": 2000000, "desc": "百万字长篇网文"},
        {"name": "虐心言情", "genre": "言情", "style": "伤感", "words": 40000, "desc": "情感细腻、有遗憾感"},
        {"name": "紧张悬疑", "genre": "悬疑", "style": "紧张", "words": 60000, "desc": "节奏快、悬念密"},
    ]
    table = Table(title="推荐题材 + 文风组合")
    table.add_column("模板名")
    table.add_column("题材")
    table.add_column("文风")
    table.add_column("字数")
    table.add_column("风格描述")
    for t in templates:
        table.add_row(t["name"], t["genre"], t["style"], f"{t['words'] // 1000}K", t["desc"])
    console.print(table)
    console.print("\n[dim]用法示例：[/dim]")
    console.print("  novel init my_novel --title '冬夜的灰' --genre 悬疑 --style 冷峻 --words 80000")
    console.print("  novel webnovel-pack xianxia --title '凡人修仙' --theme '凡人逆袭' --idea '残破玉佩'")


if __name__ == "__main__":
    app()
