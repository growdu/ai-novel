"""小说生成主流程。整合大纲、人物、章节生成与多轮迭代。"""
from __future__ import annotations
import re
from dataclasses import dataclass
from . import prompts as P
from . import storage as S
from .config import GlobalConfig
from .llm import LLMClient

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
    )
    msgs = P.build_chapter_messages(chapter_ctx)
    if verbose:
        print("[write] 首轮生成...")
    result = client.chat(msgs, temperature=0.95)
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
