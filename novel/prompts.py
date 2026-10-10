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

def build_chapter_messages(ctx):
    sys_parts = [de_ai_flavour(), "", "## 你的具体任务：写一章小说", chapter()]
    if ctx.style:
        sys_parts.extend(["", "## 本项目文风", ctx.style])
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
_NO_THINK_HINT = "\n[系统提醒] 直接输出所要求的内容，不要任何 think 块或思考性话语。\n"
