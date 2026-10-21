"""骨架章补写驱动：用内核的 LLM 客户端 + 去 AI 味规则 + 质量门 + criteria 评估，把
第一章正文从骨架/提纲补成 3000+ 字成稿。

为什么不用 `novel chapter`：
    它是按大纲**整章重写**的，会丢掉骨架章里已经写好的关键台词
    （例如 docs/420 的「我们赢回了今天。阿尔法开始计算明天。」是全书的收束句）。

策略（additive，绝不丢原文）：
    1. 从现有正文里挑 3-5 个**唯一**的锚点句，均匀分布
    2. 从**最后一个锚点往前**逐个插入新场景 —— 往后插不会让前面锚点的位置失效
    3. 每轮插入后重新检查字数，达标即停
    4. 插入走 `content[:end] + 新场景 + content[end:]`，原文逐字保留

每条消息的构成（内核资产全用上）：
    P.de_ai_flavour()  内核 6.4KB 去 AI 味规则
    .novel/style.md   本项目文风
    .novel/world.md   世界观硬规则
    .novel/characters.md  人物档案
    chapter_plans/NNNN.md  本章规划
    现有正文 + 锚点 + 上一章结尾

用法：
    python3 tools/backfill.py --range 240-260            # 补写一批
    python3 tools/backfill.py --all --grade 提纲         # 所有提纲级（<800字）
    python3 tools/backfill.py --range 240-250 --dry-run  # 只看会做什么
    python3 tools/backfill.py --range 240-260 --max-rounds 4 --words 3500
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from novel import prompts as P  # noqa: E402
from novel import quality_gates as Q  # noqa: E402
from novel import storage as S  # noqa: E402
from novel.config import load_global  # noqa: E402
from novel.criteria import evaluate_via_llm, format_feedback_for_next_iter, load_criteria  # noqa: E402
from novel.llm import LLMClient, Message  # noqa: E402

PART1 = REPO / "text/yuzhou_chuanshuo/第一部_第三秩序"
KERNEL_OFFSET = 1
NO_THINK = "不要输出思考过程或任何解释，直接输出小说正文。\n\n"


# ---------------------------------------------------------------- 文本工具


def cn_words(text: str) -> int:
    return len(re.findall(r"[一-鿿]", text))


def strip_title_line(text: str) -> str:
    """去掉首行「## 第N章 标题」，插入时不能重复标题。"""
    lines = text.splitlines()
    if lines and re.match(r"^#{1,3}\s*第", lines[0].strip()):
        return "\n".join(lines[1:]).strip()
    return text.strip()


_ANCHOR_RE = re.compile(r"[^\n。！？；…]{8,60}[。！？…]|\n")


def pick_anchors(text: str, want: int) -> list[str]:
    """挑 want 个在正文里唯一出现、长度适中、分布均匀的句子当插入锚点。

    必须唯一：expand 走 content.find(after_text)，重复会插错地方。
    必须够长：太短的句子（对白）容易重复，长的叙述句更好定位。
    """
    body = strip_title_line(text)
    counts: dict[str, int] = {}
    cands: list[tuple[int, str]] = []
    for m in _ANCHOR_RE.finditer(body):
        s = m.group(0).strip()
        if not (8 <= len(s) <= 60):
            continue
        if s.startswith(("#", "-", "*", "|")):
            continue
        if re.search(r"[a-zA-Z]{3,}", s):
            continue
        cands.append((m.start(), s))
        counts[s] = counts.get(s, 0) + 1
    uniq = [(pos, s) for pos, s in cands if counts[s] == 1]
    if not uniq:
        return []
    # 均匀取点：跳过开头结尾各 10%，在中间均匀分布
    lo, hi = int(len(body) * 0.10), int(len(body) * 0.90)
    span = [x for x in uniq if lo <= x[0] <= hi] or uniq
    if len(span) <= want:
        return [s for _, s in span]
    step = len(span) / want
    return [span[int(i * step)][1] for i in range(want)]


# ---------------------------------------------------------------- 上下文


class Ctx:
    """项目级的静态上下文，只读一次。"""

    def __init__(self, proj: S.Project):
        self.proj = proj
        read = lambda p: p.read_text(encoding="utf-8") if p.exists() else ""  # noqa: E731
        self.style = read(proj.style_path)
        self.world = read(proj.world_path)
        self.characters = read(proj.characters_path)
        self.volumes = read(proj.volumes_path)
        self.state = read(proj.state_path)
        self.foreshadow = read(proj.foreshadowing_path)
        self.criteria = load_criteria(proj.novel_dir / "criteria.md")
        self.samples = _load_samples(proj)

    def plan(self, kno: int) -> str:
        p = self.proj.novel_dir / "chapter_plans" / f"{kno:04d}.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def tail_of(self, kno: int, n: int = 400) -> str:
        prev = S.load_chapter(self.proj, kno - 1) or ""
        return strip_title_line(prev)[-n:]


def _load_samples(proj: S.Project, max_chars: int = 1600) -> str:
    out = []
    for f in sorted(proj.samples_dir.glob("*.md"))[:2]:
        out.append(f.read_text(encoding="utf-8")[:max_chars])
    return "\n\n".join(out)


# ---------------------------------------------------------------- 生成


def build_insert_messages(ctx: Ctx, kno: int, content: str, anchor: str, instruction: str):
    return [
        Message("system", P.de_ai_flavour() + "\n\n## 你的具体任务：在指定句子之后插入一段新场景"),
        Message(
            "user",
            NO_THINK
            + "\n".join(
                [
                    "## 小说：%s（第一部《第七界域》，末世科幻 + 群像 + 黑色幽默）" % ctx.proj.title,
                    "",
                    "## 本项目文风",
                    ctx.style,
                    "",
                    "## 世界观硬规则",
                    ctx.world,
                    "",
                    "## 人物档案",
                    ctx.characters,
                    "",
                    "## 本章规划",
                    ctx.plan(kno) or "（无）",
                    "",
                    "## 上一章结尾（衔接用）",
                    ctx.tail_of(kno) or "（本章是第一章）",
                    "",
                    "## 本章现有正文（这是骨架，绝不可删改，只在其间补写）",
                    content,
                    "",
                    "## 插入锚点（你写的场景紧接这一句之后开始）",
                    anchor,
                    "",
                    "## 本次插入要求",
                    instruction,
                ]
            ),
        ),
    ]


INSERT_INSTRUCTION = """在这一句之后插入一个新场景，把这一章从骨架补成完整章节。

硬要求：
- 插入的是**过程**，不是摘要。读者要能看见：谁在哪、周围有什么、限制条件是什么、
  他做了什么、失败了哪一步、怎么硬扛过去的。
- 场面为主：至少给一次位移或破坏动作，一段有信息量的对话交锋，一次可见的代价。
- 严禁重复现有正文已经写过的信息和台词。
- 严禁新增主要人物；配角只用已在人物档案里出现过的。
- 不要写总结段，不要升华，不要预告下一章。
- 直接输出场景正文，不要任何标题、序号或说明。"""


def insert_scene(client: LLMClient, ctx: Ctx, kno: int, content: str, anchor: str, words: int) -> str | None:
    msgs = build_insert_messages(ctx, kno, content, anchor, INSERT_INSTRUCTION)
    try:
        res = client.chat_with_continuation(
            msgs, target_words=words, max_total_tokens=24000, temperature=0.95
        )
    except Exception as e:  # 配额／网络错误交给上层重试
        print("    [x] 调用失败：%s" % e)
        return None
    new = (res.content or "").strip()
    new = re.sub(r"^#{1,3}\s*第[0-9零一二三四五六七八九十百千]+章.*$", "", new, count=1, flags=re.M).strip()
    new = re.sub(r"^(场景|片段|插入内容)[:：].*$", "", new, count=1, flags=re.M).strip()
    return new if cn_words(new) >= 150 else None


def expand_chapter(
    client: LLMClient,
    ctx: Ctx,
    kno: int,
    target: int,
    max_rounds: int,
    anchors_per_round: int,
    feedback: str = "",
    dry_run: bool = False,
) -> tuple[int, int]:
    """把一章补到 target 字。返回 (最终字数, 实际插入次数)。"""
    orig = S.load_chapter(ctx.proj, kno) or ""
    before = cn_words(orig)
    if before >= target:
        return before, 0

    title_line = ""
    if orig.splitlines():
        title_line = orig.splitlines()[0]

    inserted = 0
    for rnd in range(1, max_rounds + 1):
        cur = S.load_chapter(ctx.proj, kno) or orig
        n = cn_words(cur)
        if n >= target:
            break
        need = target - n
        anchors = pick_anchors(cur, anchors_per_round)
        if not anchors:
            print("    [x] 找不到可用锚点，停止")
            break
        # 从后往前插：后面插入不会让前面锚点的位置失效
        per = max(300, need // max(1, len(anchors)))
        if dry_run:
            print("    [dry] 第%d轮 需补 %d 字，%d 个锚点，每处约 %d 字" % (rnd, need, len(anchors), per))
            for a in anchors:
                print("           锚点：%s" % a[:40])
            break
        fb = ("\n【上一轮质量反馈，必须落地】\n" + feedback) if feedback else ""
        for a in reversed(anchors):
            if cn_words(S.load_chapter(ctx.proj, kno) or "") >= target:
                break
            instr = INSERT_INSTRUCTION + fb
            scene = insert_scene(client, ctx, kno, S.load_chapter(ctx.proj, kno) or cur, a, per)
            if not scene:
                continue
            cur = S.load_chapter(ctx.proj, kno) or cur
            idx = cur.find(a)
            if idx < 0:
                print("    [x] 锚点失效（可能被改动），跳过")
                continue
            end = idx + len(a)
            updated = cur[:end].rstrip() + "\n\n" + scene + "\n\n" + cur[end:].lstrip("\n")
            S.save_chapter(ctx.proj, kno, updated)
            inserted += 1
            print("    [+] 插入 %d 字 → 本章 %d 字" % (cn_words(scene), cn_words(updated)))

    final = S.load_chapter(ctx.proj, kno) or orig
    # 标题行被插坏就修回去
    if title_line and not final.splitlines()[0].strip().startswith("##"):
        S.save_chapter(ctx.proj, kno, title_line + "\n\n" + strip_title_line(final))
        final = S.load_chapter(ctx.proj, kno)
    return cn_words(final), inserted


# ---------------------------------------------------------------- 选章


def select(ctx: Ctx, rng: tuple[int, int] | None, grades: set[str], only_below: int) -> list[int]:
    out = []
    for kno in range(1, 422):
        if rng and not (rng[0] <= kno <= rng[1]):
            continue
        c = S.load_chapter(ctx.proj, kno)
        if c is None:
            continue
        n = cn_words(c)
        if n >= only_below:
            continue
        if grades and grade_of(n) not in grades:
            continue
        out.append(kno)
    return out


def grade_of(n: int) -> str:
    if n >= 2600:
        return "成稿"
    if n >= 1800:
        return "待增补"
    if n >= 800:
        return "骨架"
    return "提纲"


# ---------------------------------------------------------------- 主流程


def main() -> None:
    ap = argparse.ArgumentParser(description="《第七界域》骨架章补写驱动")
    ap.add_argument("--range", dest="rng", help="内核章节号区间，如 240-260")
    ap.add_argument("--all", action="store_true", help="全部章节")
    ap.add_argument("--grade", nargs="*", default=[], choices=["成稿", "待增补", "骨架", "提纲"])
    ap.add_argument("--only-below", type=int, default=3000, help="只处理低于此字数的章")
    ap.add_argument("--words", type=int, default=3200, help="补到的目标字数")
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--anchors", type=int, default=3, help="每轮插几处")
    ap.add_argument("--batch", type=int, default=10, help="每多少章跑一次 criteria 评估")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stop-file", default="", help="出现该文件则停止（.novel/stop_backfill）")
    args = ap.parse_args()

    rng = None
    if args.rng:
        a, _, b = args.rng.partition("-")
        rng = (int(a), int(b or a))
    if not rng and not args.all and not args.grade:
        ap.error("要给 --range / --all / --grade 至少一个")

    proj = S.load_project(PART1)
    ctx = Ctx(proj)
    cfg = load_global()
    if cfg.dry_run:
        print("[!] DRY_RUN=true，不会真正调用 API")
    client = LLMClient(cfg)

    todo = select(ctx, rng, set(args.grade), args.only_below)
    print(f"计划处理 {len(todo)} 章（目标 {args.words} 字，内核号 {todo[0] if todo else '-'} 起）")
    if not todo:
        return

    stop = PART1 / ".novel/stop_backfill"
    feedback = ""
    done = failed = 0
    t0 = time.time()

    for i, kno in enumerate(todo, 1):
        if args.stop_file and stop.exists():
            print("\n[stop] 检测到停止文件，退出")
            break
        fno = kno - KERNEL_OFFSET
        cur = S.load_chapter(proj, kno) or ""
        head = cur.splitlines()[0] if cur.splitlines() else ""
        print(f"\n[{i}/{len(todo)}] 内核{kno} docs/{fno:03d} {head[:30]} （现 {cn_words(cur)} 字 · {grade_of(cn_words(cur))}）")
        try:
            words, ins = expand_chapter(
                client, ctx, kno, args.words, args.max_rounds, args.anchors, feedback, args.dry_run
            )
            ok = words >= args.only_below
            done += ok
            failed += not ok
            print(f"    → {words} 字（插入 {ins} 次）{'✓' if ok else '✗ 仍不足'}")
        except KeyboardInterrupt:
            print("\n[中断]")
            break
        except Exception as e:
            failed += 1
            print("    [x] 异常：%s" % e)
            time.sleep(3)

        # 每批跑一次 criteria，把反馈注入下一批
        if ctx.criteria and i % args.batch == 0 and not args.dry_run:
            print(f"\n[criteria] 评估最近 {args.batch} 章…")
            blob = "\n\n".join(
                (S.load_chapter(proj, k) or "") for k in todo[max(0, i - args.batch) : i]
            )
            try:
                rep = evaluate_via_llm(ctx.criteria, blob, feedback, client=client)
                feedback = format_feedback_for_next_iter(rep)
                (proj.novel_dir / "last_criteria.json").write_text(
                    json.dumps(rep.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print("  摘要：%s" % rep.summary[:160])
                print("  优先修：%s" % ("；".join(rep.top_priority_fixes[:3]) or "（无）"))
            except Exception as e:
                print("  [x] criteria 评估失败：%s" % e)

    el = time.time() - t0
    print(f"\n=== 完成 {done} 章，未达标 {failed} 章，用时 {el/60:.1f} 分钟 ===")
    print("刷新台账：python3 tools/gap_ledger.py")


if __name__ == "__main__":
    sys.exit(main())