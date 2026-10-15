"""项目初始化入口：init / write / webnovel_pack + 内部 helper。

v0.13.x 这三个是用户最常用入口；write 还是端到端流水线触发点。
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from novel.config import load_global
from novel import generator as G
from novel import storage as S
from novel.llm import LLMClient


console = Console()


def _run_auto_via_spec(
    spec, project_dir: Path, cfg, budget: float,
    plans_only: bool, skip_plans: bool,
    serve: bool, serve_port: int,
    parallel: int = 0,
):
    """novel write / webnovel_pack --auto 内部 helper：起仪表盘（如需）+ 调 run_auto_novel。"""
    from novel.auto import run_auto_novel

    # 把 parallel 同步到 spec（防御性，避免 CLI 端到 spec 链路漏掉）
    if parallel and parallel >= 2:
        spec.parallel = parallel

    if serve:
        try:
            from novel.web import start_serve_in_thread
            start_serve_in_thread(project_dir, port=serve_port)
        except Exception as e:
            console.print(f"[yellow]仪表盘启动失败（端口 {serve_port} 占用？）：{e}[yellow]")

    try:
        out = run_auto_novel(
            spec, project_dir, cfg=cfg,
            budget_cny=budget,
            plans_only=plans_only,
            skip_plans=skip_plans,
        )
        console.print(f"\n[bold green]✅ 完稿：[/bold green] {out}")
        return out
    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断。再次跑 `novel write` 自动续跑。[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(f"[red]novel write 失败：{e}[red]")
        raise typer.Exit(1)


def init(
    name: str = typer.Argument(..., help="小说项目目录名"),
    title: str = typer.Option(None, "--title", "-t"),
    theme: str = typer.Option("", "--theme"),
    style: str = typer.Option("", "--style", "-s", help="文风：可写预设名如'搞笑' / '冷峻' / '诗意'，或自由描述"),
    words: int = typer.Option(30000, "--words", "-w"),
    genre: str = typer.Option("现实 / 严肃文学", "--genre", "-g", help="题材：玄幻/仙侠/科幻/悬疑/推理/言情/历史/武侠/都市/校园/现实/严肃文学"),
    here: bool = typer.Option(False, "--here"),
    template: str = typer.Option(None, "--template", "-T", help="用推荐模板（用 `novel templates` 看列表）"),
):
    """初始化一个新的小说项目。

    --template NAME 用预设模板填充（题材 + 文风 + 主题 + 字数）。
    例：novel init demo --template 东北悬疑
    """
    # 模板优先：用模板的值填充未指定字段
    if template:
        from novel.templates import get_template, apply_template
        tpl = get_template(template)
        if tpl is None:
            console.print(f"[red]未知模板：{template}[/red]")
            console.print("[dim]用 `novel templates` 看列表[/dim]")
            raise typer.Exit(1)
        values = apply_template(tpl, overrides={
            "title": title,
            "theme": theme,
            "genre": genre if genre != "现实 / 严肃文学" else None,
            "style": style or None,
            "words": words if words != 30000 else None,
        })
        title = values["title"] or title
        theme = values["theme"] or theme
        genre = values["genre"] or genre
        style = values["style"] or style
        words = values["words"] or words
        console.print(f"[cyan]使用模板：{tpl.name}[/cyan]  ({tpl.genre}, {tpl.style}, {tpl.default_words // 1000}K 字)")

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


def write(
    name: str = typer.Argument(None, help="项目目录名（与 --here 互斥）"),
    template: str = typer.Option(None, "--template", "-T", help="用推荐模板填充题材/文风/字数（`novel templates` 看列表）"),
    title: str = typer.Option(None, "--title", "-t", help="小说标题"),
    theme: str = typer.Option("", "--theme", help="一句话主题"),
    from_source: str = typer.Option(None, "--from-source", "-S", help="源小说 TXT/MD 文件路径（自动提骨架 + 改编）"),
    direction: str = typer.Option("换名 + 换壳", "--direction", "-d", help="模仿方向：换名/换壳/后传/反派视角/性别转换"),
    genre: str = typer.Option("现实 / 严肃文学", "--genre", "-g"),
    style: str = typer.Option("", "--style", "-s"),
    words: int = typer.Option(50000, "--words", "-w"),
    chapters: int = typer.Option(0, "--chapters", help="显式章数（0=按字数自动）"),
    quality: str = typer.Option("standard", "--quality", help="质量档：draft / standard / premium"),
    budget: float = typer.Option(0.0, "--budget", help="成本上限 CNY；0=不限"),
    serve: bool = typer.Option(False, "--serve", help="同时启动 Web 仪表盘"),
    serve_port: int = typer.Option(8765, "--serve-port"),
    plans_only: bool = typer.Option(False, "--plans-only"),
    skip_plans: bool = typer.Option(False, "--skip-plans"),
    parallel: int = typer.Option(0, "--parallel", "-P", help="并发章节 worker 数（0/1=串行，>=2=并发节省 50%+ 时间；v0.13+）"),
    here: bool = typer.Option(False, "--here"),
    force: bool = typer.Option(False, "--force", help="已存在目录强制覆盖"),
):
    """一行写完整本书：需求驱动（--title）或模仿驱动（--from-source），跑完规划→写作→润色→一致性→导出。

    --template 用预设快速填题材/文风/字数；用户参数（--title/--words/...）始终优先。
    --parallel N 开 N 个 worker 并发生成章节（I/O-bound 并发节省 50%+ 时间，DRY_RUN 模式建议 4-8）。

    Examples:
        # 需求驱动
        novel write demo --title '冬夜的灰' --theme '东北命案' --genre 悬疑 --style 冷峻 --words 60000

        # 模仿驱动
        novel write fanfic --from-source 白夜行.txt --direction 换壳 --genre 校园 --style 冷峻 --words 80000

        # 模板快速开始
        novel write quick --template 东北悬疑 --title '盘锦往事' --words 80000
    """
    # ── 0. 模板快速入口 ──
    if template:
        from novel.templates import get_template, apply_template
        tpl = get_template(template)
        if tpl is None:
            console.print(f"[red]未知模板：{template}[/red]")
            console.print("[dim]用 `novel templates` 看列表[/dim]")
            raise typer.Exit(1)
        values = apply_template(tpl, overrides={
            "title": title,
            "theme": theme,
            "genre": genre if genre != "现实 / 严肃文学" else None,
            "style": style or None,
            "words": words if words != 50000 else None,
        })
        title = values["title"] or title
        theme = values["theme"] or theme
        genre = values["genre"] or genre
        style = values["style"] or style
        words = values["words"] or words
        console.print(f"[cyan]使用模板：{tpl.name}[/cyan]  ({tpl.genre}, {tpl.style}, {tpl.default_words // 1000}K 字)")

    # ── 1. 校验：至少指定 --title 或 --from-source 之一 ──
    if title is None and from_source is None:
        console.print("[red]请指定输入：--title（需求驱动）或 --from-source（模仿驱动）[/red]")
        raise typer.Exit(1)
    if not here and name is None:
        console.print("[red]请提供 NAME 或加 --here。[/red]")
        raise typer.Exit(1)

    # ── 2. 处理 quality 档 ──
    from novel.auto_state import QualityPreset, AutoSpec
    try:
        quality_preset = QualityPreset(quality)
    except ValueError:
        console.print(f"[red]未知 quality：{quality}。可选：draft/standard/premium[/red]")
        raise typer.Exit(1)

    # ── 3. 项目目录 ──
    project_dir = Path.cwd() if here else Path.cwd() / name
    if not here and project_dir.exists() and any(project_dir.iterdir()):
        if not force:
            console.print(f"[red]目录 {project_dir} 不为空。用 --force 覆盖。[/red]")
            raise typer.Exit(1)
    project_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_global()

    # ── 4. 模仿驱动分支 ──
    if from_source is not None:
        # 4.1 读源
        src_path = Path(from_source)
        if not src_path.is_absolute():
            src_path = Path.cwd() / from_source
        if not src_path.exists():
            console.print(f"[red]源文件不存在：{src_path}[/red]")
            raise typer.Exit(1)
        source_text = src_path.read_text(encoding="utf-8")
        if not source_text.strip():
            console.print("[red]源文件内容为空。[/red]")
            raise typer.Exit(1)

        # 4.2 提骨架 + 改编
        client = LLMClient(cfg)
        console.print("[bold cyan][模仿驱动] 步骤 1/3: 提取源小说骨架...[/bold cyan]")
        skeleton_text = G.extract_skeleton(source_text, client=client)
        console.print("[bold cyan][模仿驱动] 步骤 2/3: 生成改编方案...[/bold cyan]")
        adapt_text = G.adapt_novel(source_text, direction, genre, style, client=client, skeleton_text=skeleton_text)

        # 4.3 init 项目 + 预填 outline（让 auto _planning_phase 跳过大纲生成）
        init_title = title or f"基于《{src_path.stem}》的{direction}"
        proj = S.init_project(
            project_dir, init_title, theme=theme,
            meta={"genre": genre, "target_words": words, "style_preset": style,
                  "source": from_source, "direction": direction},
        )
        proj.novel_dir.mkdir(parents=True, exist_ok=True)
        full_adapt = "# 源小说骨架\n\n" + skeleton_text + "\n\n---\n\n# 改编方案\n\n" + adapt_text
        (proj.novel_dir / "adapt.md").write_text(full_adapt, encoding="utf-8")
        proj.outline_path.write_text("# 大纲（基于模仿改编）\n\n" + adapt_text + "\n", encoding="utf-8")

        console.print(f"[bold cyan][模仿驱动] 步骤 3/3: 进入 6 阶段流水线[/bold cyan]")
        console.print(Panel.fit(
            f"[green]已创建项目（模仿驱动）[/green]\n"
            f"标题: {init_title}\n"
            f"源: {from_source}\n"
            f"方向: {direction} → {genre}/{style} ({words} 字)",
            title="novel write",
        ))

        spec = AutoSpec(
            title=init_title, theme=theme, genre=genre, style=style,
            target_words=words, target_chapters=chapters,
            quality=quality_preset, budget_cny=budget,
            parallel=parallel,
        )
        return _run_auto_via_spec(spec, project_dir, cfg, budget, plans_only, skip_plans, serve, serve_port)

    # ── 5. 需求驱动分支 ──
    proj = S.init_project(
        project_dir, title, theme=theme,
        meta={"genre": genre, "target_words": words, "style_preset": style},
    )
    spec = AutoSpec(
        title=title, theme=theme, genre=genre, style=style,
        target_words=words, target_chapters=chapters,
        quality=quality_preset, budget_cny=budget,
        parallel=parallel,
    )
    console.print(Panel.fit(
        f"[green]已创建项目（需求驱动）[/green]\n"
        f"标题: {title}\n"
        f"题材: {genre} | 文风: {style or '（默认）'} | 字数: {words}",
        title="novel write",
    ))
    return _run_auto_via_spec(spec, project_dir, cfg, budget, plans_only, skip_plans, serve, serve_port)


def webnovel_pack(
    name: str = typer.Argument(..., help="项目目录名"),
    title: str = typer.Option(..., "--title", "-t", help="小说标题"),
    theme: str = typer.Option(..., "--theme", help="一句话主题"),
    sub_genre: str = typer.Option("修仙 / 玄幻（网文风）", "--genre", "-g", help="网文子题材（用 webnovel-genres 查看）"),
    sub_style: str = typer.Option("经典爽文", "--style", "-y", help="爽感文风（用 webnovel-styles 查看）"),
    words: int = typer.Option(2000000, "--words", "-w"),
    idea: str = typer.Option("", "--idea", help="金手指 / 核心设定（可选）"),
    auto: bool = typer.Option(False, "--auto", help="建完项目直接跑端到端（推荐）"),
    quality: str = typer.Option("standard", "--quality", help="质量档（需 --auto）：draft / standard / premium"),
    budget: float = typer.Option(0.0, "--budget", help="成本上限 CNY（需 --auto）；0=不限"),
    parallel: int = typer.Option(0, "--parallel", "-P", help="并发章节 worker 数（需 --auto；v0.13+）"),
):
    """一键网文包：建项目 + 选网文题材 + 选爽文文风 + 写金手指 +（可选 --auto）端到端写完整本书。

    Examples:
        # 仅建项目骨架
        novel webnovel-pack my_book --title '凡人仙途' --theme '凡人逆袭' --idea '残破玉佩'

        # 建项目 + 端到端 6 阶段流水线
        novel webnovel-pack my_book --title '凡人仙途' --theme '凡人逆袭' --idea '残破玉佩' \\
            --auto --genre 修仙 --style 经典爽文 --words 500000 --quality premium
    """
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
    if not auto:
        console.print("\n[dim]下一步：[/dim]")
        console.print("  1. cd " + str(target))
        console.print("  2. novel outline")
        console.print("\n[dim]提示：加 --auto 一行写完整本网文。[/dim]")
        return
    # --auto 路径：把 webnovel_plan 内容预填到 outline
    from novel.auto_state import QualityPreset, AutoSpec
    webnovel_plan = (target / ".novel" / "webnovel_plan.md").read_text(encoding="utf-8")
    outline_path = target / ".novel" / "outline.md"
    if not outline_path.exists() or outline_path.stat().st_size < 200:
        outline_path.write_text("# 大纲（网文样板）\n\n" + webnovel_plan + "\n", encoding="utf-8")
    try:
        qp = QualityPreset(quality)
    except ValueError:
        console.print(f"[red]未知 quality：{quality}。可选：draft/standard/premium[/red]")
        raise typer.Exit(1)
    spec = AutoSpec(
        title=title, theme=theme, genre=sub_genre, style=sub_style,
        target_words=words, target_chapters=0,
        quality=qp, budget_cny=budget, parallel=parallel,
    )
    from novel.auto import run_auto_novel
    cfg = load_global()
    try:
        out = run_auto_novel(spec, target, cfg=cfg, budget_cny=budget)
        console.print(f"\n[bold green]✅ 网文完稿：[/bold green] {out}")
        return out
    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断。再次跑 `novel write " + str(target.name) + " --auto` 续跑。[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(f"[red]网文自动写作失败：{e}[/red]")
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    """注册 init / write / webnovel-pack 命令。"""
    app.command()(init)
    app.command(name="write")(write)
    app.command(name="webnovel-pack")(webnovel_pack)
