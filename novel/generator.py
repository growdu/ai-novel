"""小说生成主流程。整合大纲、人物、章节生成与多轮迭代。"""
from __future__ import annotations
import re
from dataclasses import dataclass
from . import prompts as P
from . import storage as S
from .config import GlobalConfig
from .llm import LLMClient

_META_PREFIX = "[重要] 你的任务是输出结构化的元数据（伏笔簿/弧线/时间线/世界观/分卷），不是小说正文。直接按上面要求的格式回答，不要写小说、对话、场景描写。\n\n"

def update_state(project, client=None, lookback=3):
    """从最近 lookback 章压缩出故事状态，保存到 state.md。"""
    client = client or LLMClient(GlobalConfig())
    chapters = project.list_chapters()
    if not chapters:
        return None
    recent = chapters[-lookback:]
    blobs = []
    for p in recent:
        try:
            blobs.append("### " + p.stem + "\n" + p.read_text(encoding="utf-8"))
        except Exception:
            continue
    if not blobs:
        return None
    outline = project.outline_path.read_text(encoding="utf-8") if project.outline_path.exists() else ""
    from novel.llm import Message
    sys_msg = P.de_ai_flavour() + "\n\n## 你的具体任务：压缩故事状态\n\n" + P.state()
    user = "[重要] 输出结构化元数据（状态摘要），不是小说正文。直接按格式输出，不要写小说片段。\n\n## 全书大纲\n" + outline + "\n\n## 最近章节正文\n" + "\n\n".join(blobs)
    msgs = [Message("system", sys_msg), Message("user", user)]
    res = client.chat(msgs, temperature=0.3, max_tokens=10000)
    project.state_path.write_text("# 故事状态\n\n" + res.content + "\n", encoding="utf-8")
    return res.content

def update_foreshadow(project, client=None, lookback=2):
    """重新生成伏笔簿。"""
    client = client or LLMClient(GlobalConfig())
    outline = project.outline_path.read_text(encoding="utf-8") if project.outline_path.exists() else ""
    existing = project.foreshadowing_path.read_text(encoding="utf-8") if project.foreshadowing_path.exists() else ""
    chapters = project.list_chapters()
    recent = chapters[-lookback:] if chapters else []
    blobs = [("### " + p.stem + "\n" + p.read_text(encoding="utf-8")) for p in recent]
    from novel.llm import Message
    sys_msg = P.de_ai_flavour() + "\n\n## 你的具体任务：维护伏笔簿\n\n" + P.foreshadow()
    user = _META_PREFIX + "## 大纲\n" + outline + "\n\n## 当前伏笔簿\n" + existing + "\n\n## 最近章节\n" + "\n\n".join(blobs)
    msgs = [Message("system", sys_msg), Message("user", user)]
    res = client.chat(msgs, temperature=0.3, max_tokens=10000)
    project.foreshadowing_path.write_text("# 伏笔簿\n\n" + res.content + "\n", encoding="utf-8")
    return res.content

def update_arc(project, client=None, lookback=3):
    """更新主要人物弧线总览。"""
    client = client or LLMClient(GlobalConfig())
    outline = project.outline_path.read_text(encoding="utf-8") if project.outline_path.exists() else ""
    characters = project.characters_path.read_text(encoding="utf-8") if project.characters_path.exists() else ""
    overview_path = project.arcs_dir / "_overview.md"
    existing = overview_path.read_text(encoding="utf-8") if overview_path.exists() else ""
    chapters = project.list_chapters()
    recent = chapters[-lookback:] if chapters else []
    blobs = [("### " + p.stem + "\n" + p.read_text(encoding="utf-8")) for p in recent]
    from novel.llm import Message
    sys_msg = P.de_ai_flavour() + "\n\n## 你的具体任务：维护人物弧线\n\n" + P.arc()
    user = _META_PREFIX + "## 大纲\n" + outline + "\n\n## 人物志\n" + characters + "\n\n## 当前弧线\n" + existing + "\n\n## 最近章节\n" + "\n\n".join(blobs)
    msgs = [Message("system", sys_msg), Message("user", user)]
    res = client.chat(msgs, temperature=0.3, max_tokens=10000)
    overview_path.write_text("# 人物弧线总览\n\n" + res.content + "\n", encoding="utf-8")
    return res.content

def generate_world(project, theme, genre, client=None):
    client = client or LLMClient(GlobalConfig())
    outline = project.outline_path.read_text(encoding="utf-8") if project.outline_path.exists() else ""
    from novel.llm import Message
    sys_msg = P.de_ai_flavour() + "\n\n## 你的具体任务：生成世界观\n\n" + P.world()
    user = _META_PREFIX + "## 主题\n" + theme + "\n\n## 类型\n" + genre + "\n\n## 大纲\n" + outline
    msgs = [Message("system", sys_msg), Message("user", user)]
    res = client.chat(msgs, temperature=0.8, max_tokens=10000)
    project.world_path.write_text("# 世界观\n\n" + res.content + "\n", encoding="utf-8")
    return res.content

def generate_timeline(project, client=None, lookback=5):
    client = client or LLMClient(GlobalConfig())
    outline = project.outline_path.read_text(encoding="utf-8") if project.outline_path.exists() else ""
    existing = project.timeline_path.read_text(encoding="utf-8") if project.timeline_path.exists() else ""
    chapters = project.list_chapters()
    recent = chapters[-lookback:] if chapters else []
    blobs = [("### " + p.stem + "\n" + p.read_text(encoding="utf-8")) for p in recent]
    from novel.llm import Message
    sys_msg = P.de_ai_flavour() + "\n\n## 你的具体任务：维护时间线\n\n" + P.timeline()
    user = _META_PREFIX + "## 大纲\n" + outline + "\n\n## 当前时间线\n" + existing + "\n\n## 最近章节\n" + "\n\n".join(blobs)
    msgs = [Message("system", sys_msg), Message("user", user)]
    res = client.chat(msgs, temperature=0.3, max_tokens=10000)
    project.timeline_path.write_text("# 时间线\n\n" + res.content + "\n", encoding="utf-8")
    return res.content

def generate_volumes(project, client=None):
    client = client or LLMClient(GlobalConfig())
    outline = project.outline_path.read_text(encoding="utf-8") if project.outline_path.exists() else ""
    characters = project.characters_path.read_text(encoding="utf-8") if project.characters_path.exists() else ""
    from novel.llm import Message
    sys_msg = P.de_ai_flavour() + "\n\n## 你的具体任务：分卷\n\n" + P.volume()
    user = _META_PREFIX + "## 大纲\n" + outline + "\n\n## 人物志\n" + characters
    msgs = [Message("system", sys_msg), Message("user", user)]
    res = client.chat(msgs, temperature=0.7, max_tokens=10000)
    project.volumes_path.write_text("# 分卷\n\n" + res.content + "\n", encoding="utf-8")
    return res.content
@dataclass
class OutlineRequest:
    title: str
    theme: str
    genre: str = "现实"
    target_words: int = 30000
    characters: str = ""
    extra: str = ""

@dataclass
class CharacterRequest:
    outline_text: str
    existing: str = ""
    extra: str = ""

@dataclass
class ChapterRequest:
    chapter_no: int
    target_words: int = 3000

@dataclass
class ChapterResult:
    chapter_no: int
    content: str
    detect_report: str = ""
    review_report: str = ""
    iterations: int = 1
    word_count: int = 0
    history: list = None
    def __post_init__(self):
        if self.history is None:
            self.history = []

def generate_outline(req, client=None):
    client = client or LLMClient(GlobalConfig())
    msgs = P.build_outline_messages(req.title, req.theme, req.genre, req.target_words, req.characters, req.extra)
    return client.chat(msgs, temperature=0.85)

def generate_characters(req, client=None):
    client = client or LLMClient(GlobalConfig())
    msgs = P.build_character_messages(req.outline_text, req.existing, req.extra)
    return client.chat(msgs, temperature=0.85)

_CHAPTER_SPLIT_RE = re.compile(r"\n(?=#\s*(?:第[一二三四五六七八九十百千]+章|[0-9]{1,3}|[一二三四五六七八九十]+))")

def parse_chapter_plan(outline_text, chapter_no):
    if not outline_text:
        return "（暂无本章规划，按需生成）"
    parts = _CHAPTER_SPLIT_RE.split(outline_text)
    parts = [p for p in parts if p.strip()]
    idx = chapter_no - 1
    if 0 <= idx < len(parts):
        return parts[idx].strip()
    return parts[-1].strip() if parts else outline_text.strip()

def write_chapter(req, ctx, client=None, max_iters=2, do_detect=True, do_polish=True, verbose=True):
    client = client or LLMClient(GlobalConfig())
    chapter_ctx = P.ChapterContext(
        title=ctx["title"],
        outline=ctx["outline"],
        characters=ctx["characters"],
        style=ctx["style"],
        chapter_plan=ctx["chapter_plan"],
        prev_chapter_tail=ctx["prev_chapter_tail"],
        target_words=req.target_words,
        state=ctx.get("state", ""),
        foreshadow=ctx.get("foreshadow", ""),
        world=ctx.get("world", ""),
        timeline=ctx.get("timeline", ""),
        volumes=ctx.get("volumes", ""),
        arc=ctx.get("arc", ""),
        chapter_index_in_volume=ctx.get("chapter_index_in_volume", 0),
        total_chapters_in_volume=ctx.get("total_chapters_in_volume", 0),
    )
    msgs = P.build_chapter_messages(chapter_ctx)
    if verbose:
        print("[write] 首轮生成...")
    # 长篇写作需要足够 token（minimax-M3 是推理型，大量 token 被 think 吃掉）
    chapter_budget = max(8000, req.target_words * 3)
    result = client.chat(msgs, temperature=0.95, max_tokens=chapter_budget)
    content = _strip_meta(result.content)
    history = [("v1", content)]
    detect_report = ""
    review_report = ""
    iters = 1
    for i in range(max_iters):
        if do_detect:
            if verbose:
                print("[detect] 检测 AI 味...")
            d_msgs = P.build_detect_messages(content)
            detect_report = client.chat(d_msgs, temperature=0.3).content
            if verbose:
                _print_short(detect_report, head="[AI 味检测报告]")
        if verbose:
            print("[review] 审稿...")
        r_msgs = P.build_review_messages(content, chapter_ctx.chapter_plan, chapter_ctx.prev_chapter_tail)
        review_report = client.chat(r_msgs, temperature=0.4).content
        if verbose:
            _print_short(review_report, head="[审稿报告]")
        if i + 1 >= max_iters:
            break
        if not _needs_more_iter(review_report):
            if verbose:
                print("[review] 未发现严重问题，停止迭代。")
            break
        if do_polish:
            if verbose:
                print("[polish] 润色重写...")
            p_msgs = P.build_polish_messages(content, chapter_ctx.chapter_plan, chapter_ctx.prev_chapter_tail, detect_report, "")
            content = _strip_meta(client.chat(p_msgs, temperature=0.9).content)
            iters += 1
            history.append(("v%d_polish" % iters, content))
    return ChapterResult(
        chapter_no=req.chapter_no,
        content=content,
        detect_report=detect_report,
        review_report=review_report,
        iterations=iters,
        word_count=S.chapter_word_count(content),
        history=history,
    )

def write_chapter_extended(req, ctx, project=None, client=None, max_iters=2, update_after=True, verbose=True):
    """长篇版 write_chapter：写完后自动更新 state、foreshadow、arc。
    update_after=True 时，每章写完会调用 LLM 压缩一次全局状态。
    """
    client = client or LLMClient(GlobalConfig())
    res = write_chapter(req, ctx, client=client, max_iters=max_iters, verbose=verbose)
    if project and update_after:
        try:
            if verbose:
                print("[state] 更新故事状态摘要...")
            update_state(project, client=client, lookback=3)
        except Exception as e:
            if verbose:
                print("[state] 更新失败: " + str(e))
        try:
            if verbose:
                print("[foreshadow] 更新伏笔簿...")
            update_foreshadow(project, client=client, lookback=2)
        except Exception as e:
            if verbose:
                print("[foreshadow] 更新失败: " + str(e))
        try:
            if verbose:
                print("[arc] 更新人物弧线...")
            update_arc(project, client=client, lookback=3)
        except Exception as e:
            if verbose:
                print("[arc] 更新失败: " + str(e))
    return res

def _needs_more_iter(review_text):
    bad_signals = ["严重", "硬伤", "AI 味", "AI味", "太多", "全章", "几乎", "整体"]
    return any(s in review_text for s in bad_signals)

def _strip_meta(text):
    lines = text.splitlines()
    drop_prefixes = ("以下是", "下面", "好的", "这是")
    while lines:
        s = lines[0].strip()
        if not s:
            break
        if s.startswith(drop_prefixes) or len(s) < 3:
            lines.pop(0)
        else:
            break
    while lines and lines[-1].strip() in ("本章完", "（本章完）", "（完）", "[本章完]"):
        lines.pop()
    return "\n".join(lines).strip()

def _print_short(text, n=12, head=""):
    if head:
        print("\n" + head)
    print("\n".join(text.splitlines()[:n]))
    if len(text.splitlines()) > n:
        print("...（以下省略）")
