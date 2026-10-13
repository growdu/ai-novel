"""小说生成主流程。整合大纲、人物、章节生成与多轮迭代。"""
from __future__ import annotations
import re
from dataclasses import dataclass
from . import prompts as P
from . import storage as S
from .config import GlobalConfig
from .llm import LLMClient

_META_PREFIX = "[重要] 你的任务是输出结构化的元数据（伏笔簿/弧线/时间线/世界观/分卷），不是小说正文。直接按上面要求的格式回答，不要写小说、对话、场景描写。\n\n"

def load_style_samples(project, max_samples=2, max_chars=2000):
    """从 .novel/samples/ 加载风格样本片段。"""
    samples_dir = project.samples_dir
    if not samples_dir.exists():
        return ""
    import os
    files = sorted(samples_dir.glob("*.md"))
    if not files:
        return ""
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    import random
    selected = files[:max(3, max_samples)]
    random.shuffle(selected)
    selected = selected[:max_samples]
    blobs = []
    total = 0
    for f in selected:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if not text.strip():
            continue
        if len(text) > max_chars // max_samples:
            text = text[:max_chars // max_samples]
        blobs.append("### 样本：%s\n%s" % (f.name, text))
        total += len(text)
        if total >= max_chars:
            break
    if not blobs:
        return ""
    return "[重要] 以下是作者手写的风格样本片段，你必须深度模仿这个语感来写本次章节。\n\n" + "\n\n---\n\n".join(blobs)

def find_stuck_chapters(project, threshold=100):
    """找出异常的章节（字数过少或包含 think 残片）。"""
    stuck = []
    for c in project.list_chapters():
        n = int(c.stem)
        text = c.read_text(encoding="utf-8")
        wc = S.chapter_word_count(text)
        if wc < threshold or "<think>" in text or " 区块" in text or ("OK so" in text[:200] or "Let me" in text[:200]):
            stuck.append((n, wc, text))
    return stuck

def export_combined(project, fmt="md", output_path=None):
    """合并所有章节为单一文件。"""
    chapters = project.list_chapters()
    if not chapters:
        return None
    titles = S.load_titles(project)
    if output_path is None:
        ext = ".md" if fmt == "md" else ".txt"
        output_path = project.root / ("book" + ext)
    if fmt == "md":
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("# " + project.title + "\n\n")
            f.write("> 主题: " + project.meta.get("theme", "") + "\n")
            f.write("> 类型: " + project.meta.get("genre", "") + "\n")
            if project.meta.get("target_words"):
                f.write("> 目标字数: " + str(project.meta["target_words"]) + "\n")
            f.write("\n---\n\n")
            for c in chapters:
                n = int(c.stem)
                t = titles.get("%04d" % n, "")
                f.write("## 第 " + str(n) + " 章 " + (t if t else "") + "\n\n")
                f.write(c.read_text(encoding="utf-8").strip())
                f.write("\n\n---\n\n")
    else:
        with open(output_path, "w", encoding="utf-8") as f:
            for c in chapters:
                f.write(c.read_text(encoding="utf-8").strip())
                f.write("\n\n")
    return output_path

def chat_assistant(project, chapter_no, instruction, client=None):
    """协作修改助手。"""
    client = client or LLMClient(GlobalConfig())
    content = S.load_chapter(project, chapter_no)
    if not content:
        return None
    prev = S.load_chapter(project, chapter_no - 1)
    prev_tail = prev[-200:] if prev else ""
    msgs = P.build_chat_assistant_messages(chapter_no, content, prev_tail, instruction)
    res = client.chat_with_continuation(
        msgs,
        target_words=len(content) // 3,
        max_total_tokens=20000,
        temperature=0.9,
    )
    new_text = _strip_meta(res.content)
    S.save_chapter(project, chapter_no, new_text)
    return new_text

def continue_chapter(project, chapter_no, instruction, client=None, target_words=1200):
    """在已有章节末尾接写一段新内容。"""
    client = client or LLMClient(GlobalConfig())
    content = S.load_chapter(project, chapter_no)
    if not content:
        return None
    after_tail = content[-200:]
    state_blob = project.state_path.read_text(encoding="utf-8") if project.state_path.exists() else ""
    chapter_plan = parse_chapter_plan(project.outline_path.read_text(encoding="utf-8") if project.outline_path.exists() else "", chapter_no)
    msgs = P.build_continue_chapter_messages(after_tail, content, state_blob, chapter_plan, instruction)
    res = client.chat_with_continuation(
        msgs,
        target_words=target_words,
        max_total_tokens=20000,
        temperature=0.95,
    )
    new_text = (res.content or "").strip()
    updated = content.rstrip() + "\n\n" + new_text
    S.save_chapter(project, chapter_no, updated)
    return new_text

def generate_chapter_plan(project, chapter_no, client=None, feedback=""):
    """细化某章的章节大纲：输出 200-400 字具体场景规划。"""
    client = client or LLMClient(GlobalConfig())
    outline_blob = project.outline_path.read_text(encoding="utf-8") if project.outline_path.exists() else ""
    coarse_plan = parse_chapter_plan(outline_blob, chapter_no)
    state_blob = project.state_path.read_text(encoding="utf-8") if project.state_path.exists() else ""
    characters_blob = project.characters_path.read_text(encoding="utf-8") if project.characters_path.exists() else ""
    msgs = P.build_chapter_plan_messages(chapter_no, outline_blob, coarse_plan, state_blob, characters_blob, feedback)
    res = client.chat_with_continuation(msgs, target_words=400, max_total_tokens=10000, temperature=0.7)
    p = project.novel_dir / "chapter_plans" / ("%04d.md" % chapter_no)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# 第 %d 章细化大纲\n\n" % chapter_no + res.content + "\n", encoding="utf-8")
    return res.content

def expand_scene(project, chapter_no, after_text, instruction, client=None, target_words=800):
    """交互式扩展：在 after_text 之后接写一段新场景。"""
    client = client or LLMClient(GlobalConfig())
    content = S.load_chapter(project, chapter_no)
    if not content:
        return None
    idx = content.find(after_text)
    if idx < 0:
        return None
    end_of_after = idx + len(after_text)
    before_tail = content[end_of_after:end_of_after + 200]
    msgs = P.build_expand_scene_messages(after_text, before_tail, content, instruction)
    res = client.chat_with_continuation(
        msgs,
        target_words=target_words,
        max_total_tokens=20000,
        temperature=0.95,
    )
    new_text = (res.content or "").strip()
    updated = content[:end_of_after] + "\n\n" + new_text + "\n\n" + content[end_of_after:]
    S.save_chapter(project, chapter_no, updated)
    return new_text

def style_radar(project, chapter_no, client=None):
    """风格雷达：评估某章与 samples 的风格相似度。"""
    client = client or LLMClient(GlobalConfig())
    content = S.load_chapter(project, chapter_no)
    if not content:
        return None
    samples = project.samples_dir.glob("*.md") if project.samples_dir.exists() else []
    sample_blobs = []
    for f in sorted(samples):
        if f.name.startswith("_"):
            continue
        try:
            sample_blobs.append("### " + f.name + "\n" + f.read_text(encoding="utf-8"))
        except Exception:
            continue
    samples_blob = "\n\n---\n\n".join(sample_blobs)
    msgs = P.build_style_radar_messages(content, samples_blob)
    res = client.chat(msgs, temperature=0.3, max_tokens=2000)
    p = project.novel_dir / "reports" / ("style_radar_%04d.md" % chapter_no)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# 第 %d 章风格雷达\n\n" % chapter_no + res.content + "\n", encoding="utf-8")
    return res.content

def generate_chapter_title(project, chapter_no, client=None, force=False):
    """为第 N 章生成标题。force=True 时重新生成；否则跳过已有标题。"""
    client = client or LLMClient(GlobalConfig())
    titles = S.load_titles(project)
    key = "%04d" % chapter_no
    if key in titles and not force:
        return titles[key]
    content = S.load_chapter(project, chapter_no)
    if not content:
        return None
    plan = parse_chapter_plan(project.outline_path.read_text(encoding="utf-8") if project.outline_path.exists() else "", chapter_no)
    existing = S.get_existing_titles(project)
    msgs = P.build_chapter_title_messages(content, plan, existing)
    res = client.chat_with_continuation(msgs, target_words=20, max_total_tokens=4000, temperature=0.5, verbose=False)
    title_lines = [l for l in (res.content or "").splitlines() if l.strip()]
    title = title_lines[0].strip().strip('"').strip("'").strip("#")[:20] if title_lines else ""
    titles[key] = title
    S.save_titles(project, titles)
    return title

def update_rolling_summary(project, client=None):
    """滚动摘要：压缩最近 30 章为整书摘要。"""
    client = client or LLMClient(GlobalConfig())
    chapters = project.list_chapters()
    if len(chapters) < 2:
        return None
    lookback = min(len(chapters), 30)
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
    characters = project.characters_path.read_text(encoding="utf-8") if project.characters_path.exists() else ""
    prev_summary = project.rolling_summary_path.read_text(encoding="utf-8") if project.rolling_summary_path.exists() else ""
    if "（暂无" in prev_summary:
        prev_summary = ""
    sys_msg = P.de_ai_flavour() + "\n\n## 你的具体任务：压缩全书滚动摘要\n\n" + P.rolling_summary()
    user = "[重要] 输出结构化元数据（滚动摘要），不是小说正文。\n\n## 全书大纲\n" + outline + "\n\n## 人物志\n" + characters + "\n\n## 当前滚动摘要\n" + prev_summary + "\n\n## 最近章节\n" + "\n\n".join(blobs)
    msgs = [Message("system", sys_msg), Message("user", user)]
    res = client.chat(msgs, temperature=0.3, max_tokens=20000)
    project.rolling_summary_path.write_text("# 滚动摘要\n\n" + res.content + "\n", encoding="utf-8")
    return res.content

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
    res = client.chat(msgs, temperature=0.3, max_tokens=20000)
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
    res = client.chat(msgs, temperature=0.3, max_tokens=20000)
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
    res = client.chat(msgs, temperature=0.3, max_tokens=20000)
    overview_path.write_text("# 人物弧线总览\n\n" + res.content + "\n", encoding="utf-8")
    return res.content

def generate_world(project, theme, genre, client=None):
    client = client or LLMClient(GlobalConfig())
    outline = project.outline_path.read_text(encoding="utf-8") if project.outline_path.exists() else ""
    from novel.llm import Message
    sys_msg = P.de_ai_flavour() + "\n\n## 你的具体任务：生成世界观\n\n" + P.world()
    user = _META_PREFIX + "## 主题\n" + theme + "\n\n## 类型\n" + genre + "\n\n## 大纲\n" + outline
    msgs = [Message("system", sys_msg), Message("user", user)]
    res = client.chat(msgs, temperature=0.8, max_tokens=20000)
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
    res = client.chat(msgs, temperature=0.3, max_tokens=20000)
    project.timeline_path.write_text("# 时间线\n\n" + res.content + "\n", encoding="utf-8")
    return res.content

def generate_volume_report(project, client=None, volume_no=1):
    """生成第 volume_no 卷的卷末报告。"""
    client = client or LLMClient(GlobalConfig())
    vol_text = project.volumes_path.read_text(encoding="utf-8") if project.volumes_path.exists() else ""
    outline_text = project.outline_path.read_text(encoding="utf-8") if project.outline_path.exists() else ""
    import re
    sections = re.split(r"(?=## 第[一二三四五六七八九十]+卷)", vol_text)
    sections = [s for s in sections if s.strip()]
    if volume_no <= len(sections):
        volume_title = sections[volume_no - 1].split("\n")[0].strip()
        volume_blocks_text = sections[volume_no - 1]
    else:
        volume_title = "第%d卷" % volume_no
        volume_blocks_text = ""
    m = re.search(r"第\s*(\d+)\s*[—\-到]\s*第?\s*(\d+)\s*章", volume_blocks_text)
    start, end = (1, 500)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
    chapters = project.list_chapters()
    blobs = []
    for c in chapters:
        n = int(c.stem)
        if start <= n <= end:
            blobs.append("### " + c.stem + "\n" + c.read_text(encoding="utf-8"))
    chapters_blob = "\n\n".join(blobs)
    foreshadow_blob = project.foreshadowing_path.read_text(encoding="utf-8") if project.foreshadowing_path.exists() else ""
    arc_blob = (project.arcs_dir / "_overview.md").read_text(encoding="utf-8") if (project.arcs_dir / "_overview.md").exists() else ""
    msgs = P.build_volume_report_messages(volume_title, chapters_blob, outline_text, foreshadow_blob, arc_blob)
    res = client.chat(msgs, temperature=0.3, max_tokens=20000)
    reports_dir = project.novel_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    p = reports_dir / ("volume_%02d_report.md" % volume_no)
    p.write_text("# 第%d卷卷末报告\n\n" % volume_no + res.content + "\n", encoding="utf-8")
    return res.content

def check_consistency(project, client=None, lookback=10):
    """跨章节一致性检查。"""
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
    world = project.world_path.read_text(encoding="utf-8") if project.world_path.exists() else ""
    characters = project.characters_path.read_text(encoding="utf-8") if project.characters_path.exists() else ""
    msgs = P.build_consistency_messages("\n\n".join(blobs), world, characters)
    res = client.chat(msgs, temperature=0.2, max_tokens=20000)
    p = project.novel_dir / "consistency_report.md"
    p.write_text("# 一致性报告\n\n" + res.content + "\n", encoding="utf-8")
    return res.content

def generate_volumes(project, client=None):
    client = client or LLMClient(GlobalConfig())
    outline = project.outline_path.read_text(encoding="utf-8") if project.outline_path.exists() else ""
    characters = project.characters_path.read_text(encoding="utf-8") if project.characters_path.exists() else ""
    from novel.llm import Message
    sys_msg = P.de_ai_flavour() + "\n\n## 你的具体任务：分卷\n\n" + P.volume()
    user = _META_PREFIX + "## 大纲\n" + outline + "\n\n## 人物志\n" + characters
    msgs = [Message("system", sys_msg), Message("user", user)]
    res = client.chat(msgs, temperature=0.7, max_tokens=20000)
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

def extract_name_roster(characters_blob):
    """从人物志 markdown 里提取人物名集合。"""
    import re
    if not characters_blob:
        return []
    name_pattern = re.compile(r"\*\*([^\*]+?)\*\*[：:]")
    items = []
    for m in name_pattern.finditer(characters_blob):
        n = m.group(1).strip()
        if 1 <= len(n) <= 10:
            items.append(n)
    return list(dict.fromkeys(items))

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
        style_samples=ctx.get("style_samples", ""),
    )
    msgs = P.build_chapter_messages(chapter_ctx)
    # 人物名强制表：注入到 system 提示词
    roster = extract_name_roster(ctx.get("characters", ""))
    if roster:
        roster_hint = "[强制] 人物名必须使用以下规范写法：" + "、".join(roster) + "。如果不得不提到其他人名，先看一遍上面的人物志。"
        msgs[0].content = msgs[0].content + "\n\n" + roster_hint
    if verbose:
        print("[write] 首轮生成...")
    # 长篇写作需要足够 token（minimax-M3 是推理型，大量 token 被 think 吃掉）
    chapter_budget = max(8000, req.target_words * 3)
    # 使用 chat_with_continuation 自动续写，避免单次响应被 think 截断导致空内容
    result = client.chat_with_continuation(
        msgs,
        target_words=req.target_words,
        max_total_tokens=chapter_budget + 16000,
        temperature=0.95,
        verbose=verbose,
    )
    content = _strip_meta(result.content)
    # 自动重试：如果首轮 think 截断导致空内容，重试最多 2 次
    auto_retry = 0
    while (not content or len(content) < 200) and auto_retry < 2:
        auto_retry += 1
        if verbose:
            print("[auto-retry] 首轮内容过短/为空，重试 #%d..." % auto_retry)
        retry_res = client.chat_with_continuation(
            msgs,
            target_words=req.target_words,
            max_total_tokens=chapter_budget + 16000,
            temperature=0.95,
        )
        content = _strip_meta(retry_res.content)
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
            feedback = "【AI 味检测】\n" + (detect_report or "（无）") + "\n\n【审稿】\n" + (review_report or "（无）")
            p_msgs = P.build_polish_messages(content, chapter_ctx.chapter_plan, chapter_ctx.prev_chapter_tail, detect_report, feedback)
            p_res = client.chat_with_continuation(p_msgs, target_words=req.target_words, max_total_tokens=20000, temperature=0.9)
            content = _strip_meta(p_res.content)
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

def write_chapter_extended(req, ctx, project=None, client=None, max_iters=2, update_after=True, verbose=True, do_polish=True):
    """长篇版 write_chapter：写完后自动更新 state、foreshadow、arc。"""
    client = client or LLMClient(GlobalConfig())
    if project and not ctx.get("style_samples"):
        ctx["style_samples"] = load_style_samples(project)
    res = write_chapter(req, ctx, client=client, max_iters=max_iters, do_polish=do_polish, verbose=verbose)
    # 注入滚动摘要（如有）
    if project:
        try:
            rs = project.rolling_summary_path.read_text(encoding="utf-8") if project.rolling_summary_path.exists() else ""
            if rs and "（暂无" not in rs:
                ctx["rolling_summary"] = rs
        except Exception:
            pass
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
        # 滚动摘要：每 5 章自动压缩一次
        try:
            chapter_count = len(project.list_chapters())
            if chapter_count >= 2 and chapter_count % 5 == 0:
                if verbose:
                    print("[rolling] 更新滚动摘要...")
                update_rolling_summary(project, client=client)
        except Exception as e:
            if verbose:
                print("[rolling] 更新失败: " + str(e))
        # 章节标题：写完每章自动生成
        try:
            if verbose:
                print("[title] 生成章节标题...")
            t = generate_chapter_title(project, req.chapter_no, client=client)
            if verbose and t:
                print("[title] 第 %d 章: %s" % (req.chapter_no, t))
        except Exception as e:
            if verbose:
                print("[title] 生成失败: " + str(e))
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
