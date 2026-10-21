"""把 text/yuzhou_chuanshuo/第一部_第三秩序 改造成内核可驱动的标准 novel 项目。

做三件事：
1. 建 .novel/ 目录骨架（chapters / chapter_plans / history / arcs / reports / samples）
2. 把 docs/000..420 软链接成 .novel/chapters/0001.md..0421.md
   —— 内核章节号是 1-based（%04d），原文件是 0-based 3 位数，偏移 +1
   —— 软链接而非拷贝：docs/ 仍是唯一真身，历史备份走 .novel/history/
3. 写 project.yaml

用法：python3 tools/build_yuzhou_project.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NOVEL_ROOT = REPO / "text" / "yuzhou_chuanshuo"
PART1 = NOVEL_ROOT / "第一部_第三秩序"
DOCS = PART1 / "docs"
NOVEL_DIR = PART1 / ".novel"
CHAPTERS = NOVEL_DIR / "chapters"

# 原文件号 -> 内核章节号偏移
KERNEL_OFFSET = 1
FIRST, LAST = 0, 420


def build_skeleton() -> None:
    for sub in ("chapters", "chapter_plans", "history", "arcs", "reports", "samples"):
        (NOVEL_DIR / sub).mkdir(parents=True, exist_ok=True)


def link_chapters() -> int:
    made, missing = 0, []
    for fno in range(FIRST, LAST + 1):
        src = DOCS / f"{fno:03d}"
        if not src.exists():
            missing.append(fno)
            continue
        kno = fno + KERNEL_OFFSET
        link = CHAPTERS / f"{kno:04d}.md"
        if link.is_symlink() or link.exists():
            continue
        link.symlink_to(Path("..") / ".." / "docs" / f"{fno:03d}")
        made += 1
    if missing:
        print(f"  ⚠ 缺原文：{missing}", file=sys.stderr)
    return made


def write_project_yaml() -> None:
    (NOVEL_DIR / "project.yaml").write_text(
        "title: 第七界域\n"
        "theme: 人类创造出更优生命后，人类是否还有不可替代性\n"
        "genre: 科幻末世\n"
        "style: 冷峻\n"
        "part: 第一部 第三秩序\n"
        "trilogy: 宇宙传说\n"
        "source_chapter_offset: 1\n",
        encoding="utf-8",
    )


def main() -> None:
    if not DOCS.exists():
        raise SystemExit(f"找不到原文目录：{DOCS}")
    build_skeleton()
    n = link_chapters()
    write_project_yaml()
    print(f"✓ .novel 骨架就绪，链接 {n} 章（内核号 0001..0421 ← docs/000..420）")
    print(f"  项目根：{PART1}")
    print(f"  后续：cd {PART1} && python3 {REPO / 'novel_cli.py'} status")


if __name__ == "__main__":
    main()