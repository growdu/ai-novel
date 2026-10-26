"""润色收敛性验证。

新门控判据是「具体问题条数 ≤ 10」。这只在 **polish 真的能减少问题条数**
时才有意义——否则高问题章永远过不了，daemon 会无限重写同一批章节。

方法：对每章做 detect → polish → detect，比较两次的问题条数与字数。
  问题条数下降 → 润色有效，循环能收敛
  不降甚至升高 → 润色无效，门控会把章节永久卡死

用法：
  python3 tools/polish_convergence.py --chapters 14 23 25 42 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novel import generator as G
from novel import prompts as P
from novel import storage as S
from novel.llm import LLMClient
from novel.quality_gates import count_ai_issues, parse_ai_flavor_score

PROJ = Path("text/yuzhou_chuanshuo/第一部_第三秩序")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=str(PROJ))
    ap.add_argument("--chapters", type=int, nargs="*", default=[14, 23, 25, 42, 5])
    args = ap.parse_args()

    project_dir = Path(args.project)
    project = S.Project(
        root=project_dir.resolve(),
        title="第七界域",
        meta=S.load_project(project_dir).meta,
    )
    client = LLMClient()
    outline_text = (
        project.outline_path.read_text(encoding="utf-8")
        if project.outline_path.exists()
        else ""
    )

    print("章  | 润色前: 问题/指数/字数 | 润色后: 问题/指数/字数 | 问题变化")
    print("-" * 78)

    for n in args.chapters:
        content = S.load_chapter(project, n)
        if not content:
            print(f"{n:3d} | (无正文，跳过)")
            continue

        plan = G.parse_chapter_plan(outline_text, n)
        prev = S.load_chapter(project, n - 1)
        prev_tail = prev[-500:] if prev else ""

        res1 = client.chat(P.build_detect_messages(content), temperature=0.3, max_tokens=2000)
        issues1 = count_ai_issues(res1.content)
        score1 = parse_ai_flavor_score(res1.content)
        words1 = S.chapter_word_count(content)

        polished = client.chat_with_continuation(
            P.build_polish_messages(content, plan, prev_tail, res1.content, ""),
            target_words=2000,
            max_total_tokens=20000,
            temperature=0.9,
        )
        new_text = (polished.content or "").strip()

        res2 = client.chat(P.build_detect_messages(new_text), temperature=0.3, max_tokens=2000)
        issues2 = count_ai_issues(res2.content)
        score2 = parse_ai_flavor_score(res2.content)
        words2 = S.chapter_word_count(new_text)

        delta = issues2 - issues1
        arrow = "↓" if delta < 0 else ("↑" if delta > 0 else "=")
        print(
            f"{n:3d} | {issues1:>4} / {score1} / {words1:>5} | "
            f"{issues2:>4} / {score2} / {words2:>5} | {delta:+3d} {arrow}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
