"""提示词加载与组合。所有原始提示词以 markdown 形式存在 prompts/ 目录。"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from .llm import Message
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

@lru_cache(maxsize=1)
def _load(name):
    p = PROMPTS_DIR / name
    if not p.exists():
        raise FileNotFoundError("提示词文件不存在: " + str(p))
    return p.read_text(encoding="utf-8")

def de_ai_flavour():
    return _load("de_ai_flavour.md")
def outline():
    return _load("outline.md")
def character():
    return _load("character.md")
def chapter():
    return _load("chapter.md")
def detect_ai():
    return _load("detect_ai.md")
def polish():
    return _load("polish.md")
def review():
    return _load("review.md")
def state():
    return _load("state.md")
def world():
    return _load("world.md")
def timeline():
    return _load("timeline.md")
def foreshadow():
    return _load("foreshadow.md")
def volume():
    return _load("volume.md")
def arc():
    return _load("arc.md")
def consistency():
    return _load("consistency.md")
def samples():
    return _load("samples.md")
def volume_report():
    return _load("volume_report.md")
def rolling_summary():
    return _load("rolling_summary.md")
def chapter_title():
    return _load("chapter_title.md")
def style_radar():
    return _load("style_radar.md")
def expand_scene():
    return _load("expand_scene.md")
def chapter_plan():
    return _load("chapter_plan.md")

@dataclass
class ChapterContext:
    title: str
    outline: str
    characters: str
    style: str
    chapter_plan: str
    prev_chapter_tail: str
    target_words: int
    feedback: str = ""
    extra: str = ""
    # 长篇专属字段
    state: str = ""
    foreshadow: str = ""
    world: str = ""
    timeline: str = ""
    volumes: str = ""
    arc: str = ""
    chapter_index_in_volume: int = 0
    total_chapters_in_volume: int = 0
    style_samples: str = ""
    rolling_summary: str = ""

def build_chapter_messages(ctx):
    sys_parts = [de_ai_flavour(), "", "## 你的具体任务：写一章小说", chapter()]
    if ctx.style:
        sys_parts.extend(["", "## 本项目文风", ctx.style])
    if ctx.style_samples:
        sys_parts.extend(["", "## 风格样本（你必须深度模仿这个语感）", ctx.style_samples, "", samples()])
    system = "\n".join(sys_parts)
    user_parts = [
        "## 小说标题：" + ctx.title,
        "",
        "## 全书大纲",
        ctx.outline or "（暂无大纲，请参考下面的人物与本章节规划）",
        "",
        "## 人物志",
        ctx.characters or "（暂无人物志，按需补）",
        "",
        "## 本章规划",
        ctx.chapter_plan,
        "",
        "## 上一章结尾（用于衔接）",
        ctx.prev_chapter_tail or "（这是第一章，从头开始）",
        "",
        "## 本章目标字数：" + str(ctx.target_words),
        "",
        "## 输出要求",
        "- 直接输出正文，不要任何前置说明、不要'以下是本章正文'、不要'本章完'。",
        "- 字数控制在目标字数的 75% 到 95%。",
    ]
    if ctx.feedback:
        user_parts.extend(["", "## 上一轮审稿的修改指令（必须落地）", ctx.feedback])
    if ctx.extra:
        user_parts.extend(["", "## 作者额外要求", ctx.extra])
    if ctx.world:
        user_parts.extend(["", "## 世界观（用于约束设定与场景）", ctx.world])
    if ctx.timeline:
        user_parts.extend(["", "## 故事内时间线（用于约束时间）", ctx.timeline])
    if ctx.volumes:
        user_parts.extend(["", "## 全书分卷（用于节奏）", ctx.volumes])
    if ctx.state:
        user_parts.extend(["", "## 上一节状态（用于跨章连贯）", ctx.state])
    if ctx.rolling_summary:
        user_parts.extend(["", "## 全书滚动摘要（用于全局视角）", ctx.rolling_summary])
    if ctx.foreshadow:
        user_parts.extend(["", "## 当前伏笔簿（用于埋设或回收钩子）", ctx.foreshadow])
    if ctx.arc:
        user_parts.extend(["", "## 核心人物弧线（用于人物变化一致）", ctx.arc])
    if ctx.chapter_index_in_volume and ctx.total_chapters_in_volume:
        user_parts.extend([
            "",
            "## 章节在卷内的位置",
            "本章是当前卷的第 %d / %d 章。请根据这个位置控制节奏：开头偏稳、中段可加冲突、收尾偏余韵。" % (ctx.chapter_index_in_volume, ctx.total_chapters_in_volume),
        ])
    user = _NO_THINK_HINT + "\n".join(user_parts)
    return [Message("system", system), Message("user", user)]

def build_outline_messages(title, theme, genre, target_words, characters, extra):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：生成或完善小说大纲\n\n" + outline()
    user_parts = [
        "## 标题：" + title,
        "## 主题：" + theme,
        "## 类型：" + genre,
        "## 目标总字数：" + str(target_words),
    ]
    if characters:
        user_parts.extend(["", "## 已有的人物关系", characters])
    if extra:
        user_parts.extend(["", "## 用户特别指定", extra])
    user_parts.extend(["", "## 输出要求", "- 直接输出大纲，不要任何元说明。", "- 章数等于目标总字数除以 3000 向上取整。"])
    user = _NO_THINK_HINT + "\n".join(user_parts)
    return [Message("system", sys), Message("user", user)]

def build_character_messages(outline_text, existing, extra):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：生成或扩展人物志\n\n" + character()
    user_parts = ["## 大纲", outline_text or "（暂无大纲）"]
    if existing:
        user_parts.extend(["", "## 已有人物志", existing])
    if extra:
        user_parts.extend(["", "## 作者特别要求", extra])
    user_parts.extend(["", "## 输出要求", "- 直接输出人物志，不要元说明。", "- 每个出场人物都覆盖。"])
    user = _NO_THINK_HINT + "\n".join(user_parts)
    return [Message("system", sys), Message("user", user)]

def build_detect_messages(content):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：检测 AI 味\n\n" + detect_ai()
    user = "## 待检测章节正文\n\n" + content
    return [Message("system", sys), Message("user", user)]

def build_polish_messages(content, chapter_plan, prev_tail, detect_report, extra):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：润色章节去除 AI 味\n\n" + polish()
    user_parts = ["## 当前章节正文", content, "", "## 本章规划", chapter_plan, "", "## 上一章结尾（用于衔接）", prev_tail or "（这是第一章）"]
    if detect_report:
        user_parts.extend(["", "## 检测报告（必须修正）", detect_report])
    if extra:
        user_parts.extend(["", "## 作者额外要求", extra])
    user_parts.extend(["", "## 输出要求", "- 直接输出重写后的完整正文。", "- 长度变化不超过正负 25%。"])
    user = _NO_THINK_HINT + "\n".join(user_parts)
    return [Message("system", sys), Message("user", user)]

def build_review_messages(content, chapter_plan, prev_tail):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：审稿并给出修改指令\n\n" + review()
    user_parts = ["## 当前章节正文", content, "", "## 本章规划", chapter_plan, "", "## 上一章结尾", prev_tail or "（这是第一章）"]
    user = _NO_THINK_HINT + "\n".join(user_parts)
    return [Message("system", sys), Message("user", user)]

def build_consistency_messages(chapters_blob, world_blob, characters_blob):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：跨章节一致性检查\n\n" + consistency()
    user_parts = ["## 已写章节", chapters_blob, "", "## 世界观", world_blob, "", "## 人物志", characters_blob]
    user = _META_PREFIX + "\n".join(user_parts)
    return [Message("system", sys), Message("user", user)]

def build_volume_report_messages(volume_title, chapters_blob, outline_blob, foreshadow_blob, arc_blob):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：生成卷末报告\n\n" + volume_report()
    user_parts = [
        "## 当前卷：" + volume_title,
        "",
        "## 本卷已写章节",
        chapters_blob or "（本卷尚未写）",
        "",
        "## 全书大纲（用于理解其他卷）",
        outline_blob,
        "",
        "## 当前伏笔簿",
        foreshadow_blob,
        "",
        "## 人物弧线总览",
        arc_blob,
    ]
    user = _META_PREFIX + "\n".join(user_parts)
    return [Message("system", sys), Message("user", user)]

def build_chapter_plan_messages(chapter_no, outline_blob, coarse_plan, state_blob, characters_blob, feedback):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：细化章节大纲\n\n" + chapter_plan()
    user_parts = [
        "## 章节号：第 " + str(chapter_no) + " 章",
        "",
        "## 全书大纲（用于理解主线与人物）",
        outline_blob,
        "",
        "## 当前要细化的粗规划",
        coarse_plan or "（无）",
        "",
        "## 上一节状态（用于衔接）",
        state_blob or "（无）",
        "",
        "## 人物志",
        characters_blob or "（无）",
    ]
    if feedback:
        user_parts.extend(["", "## 上一轮审稿意见（必须吸收）", feedback])
    user = _META_PREFIX + "\n".join(user_parts)
    return [Message("system", sys), Message("user", user)]

def build_expand_scene_messages(after_text, before_tail, full_content, instruction):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：在指定位置后接写一段新场景\n\n" + expand_scene()
    user_parts = [
        "## 已有章节正文",
        full_content,
        "",
        "## 上一句（紧接其后开始写）",
        after_text,
        "",
        "## 上一句之后 200 字上下文（用于接写理解）",
        before_tail,
        "",
        "## 作者意图",
        instruction or "（无，按场景自然延伸）",
    ]
    user = _NO_THINK_HINT + "\n".join(user_parts)
    return [Message("system", sys), Message("user", user)]

def build_style_radar_messages(chapter_content, samples_blob):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：风格雷达评分\n\n" + style_radar()
    user_parts = [
        "[重要] 直接输出评分结果，不要 think 块。\n",
        "## 新章节正文",
        chapter_content[:3000],
        "",
        "## 风格样本（参考语感）",
        samples_blob or "（无样本）",
    ]
    user = _META_PREFIX + "\n".join(user_parts)
    return [Message("system", sys), Message("user", user)]

def build_chapter_title_messages(chapter_content, chapter_plan, existing_titles):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：生成章节标题\n\n" + chapter_title()
    user_parts = [
        "[重要] 直接输出标题一行，不要其他内容。\n",
        "## 章节正文（用于提取核心物件/动作）",
        chapter_content[:2000],
        "",
        "## 本章规划",
        chapter_plan,
        "",
        "## 已用过的标题（不要重复）",
        existing_titles or "（无）",
    ]
    user = _META_PREFIX + "\n".join(user_parts)
    return [Message("system", sys), Message("user", user)]
_META_PREFIX = "[重要] 你的任务是输出结构化的元数据，不是小说正文。直接按格式回答，不要写小说片段。\n\n"
_NO_THINK_HINT = "\n[系统提醒] 直接输出所要求的内容，不要任何 think 块或思考性话语。\n"
