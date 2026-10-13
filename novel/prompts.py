"""提示词加载与组合。所有原始提示词以 markdown 形式存在 prompts/ 目录。"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
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
def genre_presets():
    return _load("genre_presets.md")
def style_presets():
    return _load("style_presets.md")
def adapt():
    return _load("adapt.md")
def fanfic():
    return _load("fanfic.md")
def skeleton():
    return _load("skeleton.md")
def webnovel_genres():
    return _load("webnovel_genres.md")
def webnovel_style():
    return _load("webnovel_style.md")
def rolling_summary():
    return _load("rolling_summary.md")
def chapter_title():
    return _load("chapter_title.md")
def style_radar():
    return _load("style_radar.md")
def expand_scene():
    return _load("expand_scene.md")
def continue_chapter():
    return _load("continue_chapter.md")
def chat_assistant():
    return _load("chat_assistant.md")
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
    genre: str = ""  # 题材（用于注入硬规则）

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
    genre_block = get_genre_block(genre)
    if genre_block:
        sys = sys + "\n\n" + genre_block
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

def build_chat_assistant_messages(chapter_no, full_content, prev_tail, instruction):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：协作修改章节\n\n" + chat_assistant()
    user_parts = [
        "## 章节号：第 " + str(chapter_no) + " 章",
        "",
        "## 作者意图",
        instruction,
        "",
        "## 上一章结尾 200 字（用于衔接）",
        prev_tail or "（这是第一章）",
        "",
        "## 当前章节正文",
        full_content,
    ]
    user = _NO_THINK_HINT + "\n".join(user_parts)
    return [Message("system", sys), Message("user", user)]

def build_continue_chapter_messages(after_tail, full_content, state_blob, chapter_plan, instruction):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：在章节末尾接写一段新内容\n\n" + continue_chapter()
    user_parts = [
        "## 已有章节正文",
        full_content,
        "",
        "## 章节末尾 200 字（从这里接写）",
        after_tail,
        "",
        "## 上一节状态摘要",
        state_blob or "（无）",
        "",
        "## 本章规划",
        chapter_plan or "（无）",
    ]
    if instruction:
        user_parts.extend(["", "## 作者意图", instruction])
    user = _NO_THINK_HINT + "\n".join(user_parts)
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
_GENRE_HEAD_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_TOTAL_TITLES = {"题材硬规则与常见设定", "文风预设", "通用建议"}

def list_genres():
    text = genre_presets()
    return [m for m in _GENRE_HEAD_RE.findall(text) if m not in _TOTAL_TITLES]

def list_styles():
    text = style_presets()
    return [m for m in _GENRE_HEAD_RE.findall(text) if m not in _TOTAL_TITLES]

_WEB_TOTAL_TITLES = {"网文题材硬规则与爽点设定", "网文爽感文风", "通用爽点节奏", "通用网文节奏"}

def list_webnovel_genres():
    text = webnovel_genres()
    return [m for m in _GENRE_HEAD_RE.findall(text) if m not in _WEB_TOTAL_TITLES]

def list_webnovel_styles():
    text = webnovel_style()
    return [m for m in _GENRE_HEAD_RE.findall(text) if m not in _WEB_TOTAL_TITLES]

def get_webnovel_genre_block(genre):
    if not genre:
        return ""
    text = webnovel_genres()
    titles = list_webnovel_genres()
    matched = _match_title(genre, titles)
    if not matched:
        return ""
    pattern = re.compile(r"^#\s+" + re.escape(matched) + r"\s*$\n(.*?)(?=^#\s+|\Z)", re.MULTILINE | re.DOTALL)
    m = pattern.search(text)
    if m:
        return "[网文题材爽点设定] " + matched + "\n" + m.group(1).strip()
    return ""

def get_webnovel_style_block(style):
    if not style:
        return ""
    text = webnovel_style()
    titles = list_webnovel_styles()
    matched = _match_title(style, titles)
    if not matched:
        return ""
    pattern = re.compile(r"^#\s+" + re.escape(matched) + r"\s*$\n(.*?)(?=^#\s+|\Z)", re.MULTILINE | re.DOTALL)
    m = pattern.search(text)
    if m:
        return "[网文爽感文风] " + matched + "\n" + m.group(1).strip()
    return ""

def get_genre_block(genre):
    if not genre:
        return ""
    text = genre_presets()
    titles = list_genres()
    matched = _match_title(genre, titles)
    if not matched:
        return ""
    pattern = re.compile(r"^#\s+" + re.escape(matched) + r"\s*$\n(.*?)(?=^#\s+|\Z)", re.MULTILINE | re.DOTALL)
    m = pattern.search(text)
    if m:
        return "[题材硬规则] " + matched + "\n" + m.group(1).strip()
    return ""

def get_style_block(style):
    if not style:
        return ""
    text = style_presets()
    titles = list_styles()
    matched = _match_title(style, titles)
    if not matched:
        return ""
    pattern = re.compile(r"^#\s+" + re.escape(matched) + r"\s*$\n(.*?)(?=^#\s+|\Z)", re.MULTILINE | re.DOTALL)
    m = pattern.search(text)
    if m:
        return "[文风指南] " + matched + "\n" + m.group(1).strip()
    return ""

def _match_title(query, titles):
        """匹配标题：精确 -> 包含 / 前缀 / 模糊"""
        if query in titles:
            return query
        for t in titles:
            if query in t or t in query:
                return t
        # 取最长公共前缀
        best = ""
        for t in titles:
            i = 0
            while i < len(query) and i < len(t) and query[i] == t[i]:
                i += 1
            if i > len(best):
                best = t[:i]
        if len(best) >= 2:
            for t in titles:
                if t.startswith(best):
                    return t
        return ""


def build_skeleton_messages(source_info):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：提取小说骨架\n\n" + skeleton()
    user = "[重要] 输出结构化骨架，不是小说正文。\n\n## 源小说信息\n" + source_info
    return [Message("system", sys), Message("user", user)]

def build_adapt_messages(source_info, skeleton_text, direction, target_genre, target_style):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：小说改编\n\n" + adapt()
    gb = get_genre_block(target_genre) if target_genre else ""
    sb = get_style_block(target_style) if target_style else ""
    if gb:
        sys = sys + "\n\n" + gb
    if sb:
        sys = sys + "\n\n" + sb
    user_parts = ["[重要] 输出结构化改编方案，不是小说正文。\n"]
    if source_info:
        user_parts.extend(["## 源小说信息", source_info, ""])
    if skeleton_text:
        user_parts.extend(["## 源小说骨架（已提取）", skeleton_text, ""])
    user_parts.extend(["## 改编方向", direction or "换名 + 换壳（保留主线，更换题材与人物名）", "", "## 目标题材", target_genre or "（与源不同）", "", "## 目标文风", target_style or "（与源不同）"])
    user = _META_PREFIX + "\n".join(user_parts)
    return [Message("system", sys), Message("user", user)]

def build_fanfic_messages(source_info, ending_state, character, era, target_words):
    sys = de_ai_flavour() + "\n\n## 你的具体任务：后传 / 番外 / 同人\n\n" + fanfic()
    user_parts = ["[重要] 输出小说正文，按源小说风格写作。\n", "## 源小说", source_info, "", "## 结尾状态", ending_state or "（未提供）", "", "## 视角人物", character or "主角", "", "## 故事时机", era or "后传：源小说结束后 5 年", "", "## 目标字数", str(target_words) if target_words else "3000"]
    user = _NO_THINK_HINT + "\n".join(user_parts)
    return [Message("system", sys), Message("user", user)]


_NO_THINK_HINT = "\n[系统提醒] 直接输出所要求的内容，不要任何 think 块或思考性话语。\n"
