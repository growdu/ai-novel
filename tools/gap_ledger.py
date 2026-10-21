"""缺口台账：逐章比对实际字数 vs 目标，输出 .novel/GAP_LEDGER.md。

分级：
  成稿 ≥2600   —— 基本达标，只需润色
  待增补 1800-2599 —— 骨架完整，缺场景厚度
  骨架 800-1799    —— 只有事件骨架，必须扩写
  提纲 <800        —— 只有结果叙述，等于没写

每批补写后重跑即可刷新。
用法：python3 tools/gap_ledger.py [--min-gap 400]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NOVEL_DIR = REPO / "text/yuzhou_chuanshuo/第一部_第三秩序/.novel"
KERNEL_OFFSET = 1
TARGET_LOW, TARGET_HIGH = 3000, 4000

GRADES = [
    ("成稿", 2600, 10 ** 9),
    ("待增补", 1800, 2600),
    ("骨架", 800, 1800),
    ("提纲", -1, 800),
]


def grade_of(n: int) -> str:
    for name, lo, hi in GRADES:
        if lo <= n < hi:
            return name
    return "成稿"


def cn_words(text: str) -> int:
    return len(re.findall(r"[一-鿿]", text))


def title_of(text: str, fallback: str) -> str:
    m = re.search(r"^#{1,3}\s*第[0-9零一二三四五六七八九十百千]+章[ 　]*(.+)$", text, re.M)
    return m.group(1).strip() if m else fallback


def collect() -> list[dict]:
    rows = []
    for p in sorted(NOVEL_DIR.joinpath("chapters").glob("[0-9]*.md")):
        kno = int(p.stem)
        text = p.read_text(encoding="utf-8")
        n = cn_words(text)
        rows.append(
            {
                "fno": kno - KERNEL_OFFSET,
                "kno": kno,
                "title": title_of(text, "（无题）"),
                "words": n,
                "grade": grade_of(n),
            }
        )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-gap", type=int, default=400, help="缺口小于此值视为达标")
    args = ap.parse_args()

    rows = collect()
    total_words = sum(r["words"] for r in rows)
    target_total = TARGET_LOW * len(rows)
    need = sum(max(0, TARGET_LOW - r["words"]) for r in rows)

    by_grade: dict[str, list[dict]] = {}
    for r in rows:
        by_grade.setdefault(r["grade"], []).append(r)

    out = [
        "# 第一部《第七界域》缺口台账",
        "",
        "> 由 `tools/gap_ledger.py` 自动生成。每批补写后重跑刷新。",
        "",
        "## 总览",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 章节数 | {len(rows)} |",
        f"| 现有中文字数 | {total_words:,} |",
        f"| 目标下限字数（{TARGET_LOW}×{len(rows)}） | {target_total:,} |",
        f"| **需补写字数** | **{need:,}** |",
        f"| 完成度 | {total_words * 100 // target_total}% |",
        "",
        "## 分级统计",
        "",
        "| 分级 | 章数 | 占比 | 该级总字数 |",
        "|------|------|------|-----------|",
    ]
    for name, _, _ in GRADES:
        g = by_grade.get(name, [])
        out.append(
            f"| {name} | {len(g)} | {len(g) * 100 // len(rows)}% | {sum(r['words'] for r in g):,} |"
        )

    out += ["", "## 分级明细", ""]
    for name, _, _ in GRADES:
        g = by_grade.get(name, [])
        if not g:
            continue
        out.append(f"### {name}（{len(g)} 章）")
        out.append("")
        if name == "成稿":
            out.append("只需润色去 AI 味，不需要补写。")
            out.append("")
            continue
        # 按章号分段列出，避免超长表格
        for i in range(0, len(g), 20):
            chunk = g[i : i + 20]
            out.append("| 章 | 标题 | 字数 | 缺口 |")
            out.append("|----|------|------|------|")
            for r in chunk:
                out.append(
                    f"| {r['fno']:03d} | {r['title']} | {r['words']} | {max(0, TARGET_LOW - r['words'])} |"
                )
            out.append("")

    todo = [r for r in rows if TARGET_LOW - r["words"] > args.min_gap]
    out += [
        "## 补写优先级",
        "",
        f"需补写 **{len(todo)}** 章。按「缺口最大优先」排前 40：",
        "",
        "| 序 | 章 | 标题 | 现字数 | 缺口 | 分级 |",
        "|----|----|------|--------|------|------|",
    ]
    for i, r in enumerate(sorted(todo, key=lambda r: r["words"])[:40], 1):
        out.append(
            f"| {i} | {r['fno']:03d} | {r['title']} | {r['words']} | {TARGET_LOW - r['words']} | {r['grade']} |"
        )

    dest = NOVEL_DIR / "GAP_LEDGER.md"
    dest.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"✓ {dest}")
    print(
        f"  {len(rows)} 章 / {total_words:,} 字 / 完成度 {total_words * 100 // target_total}%"
        f" / 需补写 {len(todo)} 章共 {need:,} 字"
    )


if __name__ == "__main__":
    sys.exit(main())