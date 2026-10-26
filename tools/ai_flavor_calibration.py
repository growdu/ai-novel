"""AI 味指数可信度验证。

回答一个问题：detect 打出的 0-100 分是**信号**还是**噪声**？

方法：取几个已知分数的章，同一 prompt 重复检测多次。
  - 自一致性：同一章多次得分是否稳定？波动大 → 分数是噪声
  - 判别力：不同章的分数是否稳定地拉开差距？拉不开 → 分数无意义

用法：
  python3 tools/ai_flavor_calibration.py --chapters 9 2 16 --repeats 3
  python3 tools/ai_flavor_calibration.py --all --repeats 3
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novel import prompts as P
from novel import storage as S
from novel.llm import LLMClient
from novel.quality_gates import parse_ai_flavor_score

PROJ = Path("text/yuzhou_chuanshuo/第一部_第三秩序")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=str(PROJ))
    ap.add_argument("--chapters", type=int, nargs="*", default=[9, 2, 16])
    ap.add_argument("--all", action="store_true", help="跑全部已有检测报告的章")
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()

    project_dir = Path(args.project)
    project = S.Project(
        root=project_dir.resolve(),
        title="第七界域",
        meta=S.load_project(project_dir).meta,
    )
    client = LLMClient()

    if args.all:
        chapters = sorted(
            int(p.stem.split("_")[1])
            for p in (project.novel_dir / "reports").glob("detect_*.md")
        )
    else:
        chapters = args.chapters

    print(f"章号 | 历史分 | 重复检测得分 | 均值 | 极差")
    print("-" * 58)

    results: dict[int, list[int]] = {}
    for n in chapters:
        content = S.load_chapter(project, n)
        if not content:
            print(f"{n:4d} | (无正文，跳过)")
            continue

        hist = "?"
        hist_file = project.novel_dir / "reports" / f"detect_{n:04d}.md"
        if hist_file.exists():
            old = parse_ai_flavor_score(hist_file.read_text(encoding="utf-8"))
            hist = str(old) if old is not None else "?"

        scores: list[int] = []
        for _ in range(args.repeats):
            res = client.chat(P.build_detect_messages(content), temperature=0.3, max_tokens=2000)
            s = parse_ai_flavor_score(res.content)
            if s is not None:
                scores.append(s)

        if not scores:
            print(f"{n:4d} | {hist:>6} | (解析失败)")
            continue

        results[n] = scores
        mean = statistics.mean(scores)
        spread = max(scores) - min(scores)
        print(f"{n:4d} | {hist:>6} | {scores} | {mean:5.1f} | {spread:4d}")

    print()
    if results:
        all_scores = [s for v in results.values() for s in v]
        print(f"全部 {len(all_scores)} 次得分：均值 {statistics.mean(all_scores):.1f}，"
              f"标准差 {statistics.pstdev(all_scores):.1f}")
        for n, v in results.items():
            if len(v) > 1:
                print(f"  第 {n} 章：组内标准差 {statistics.pstdev(v):.1f}（越大越像噪声）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
