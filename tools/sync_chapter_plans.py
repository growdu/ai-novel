"""把大纲里已有的「000-020 逐章细纲」转成内核 chapter_plans 格式。

输入：outline/第一部_第七界域_420章章节大纲.md 的「## 四、0-30章逐章细纲」一节
      （### 000 … ### 020 块，每块含 章名/剧情/场面/台词锚点/动机推进 等字段）
输出：.novel/chapter_plans/0001.md … 0021.md（内核章节号 = 原文件号 + 1）

021-030 在原大纲里只有一段合并描述（卷一开局连战段），单独处理。

用法：python3 tools/sync_chapter_plans.py [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PART1 = REPO / "text/yuzhou_chuanshuo/第一部_第三秩序"
OUTLINE = PART1 / "outline/第一部_第七界域_420章章节大纲.md"
PLANS = PART1 / ".novel/chapter_plans"
KERNEL_OFFSET = 1

# 021-030 在原大纲里是合并段，这里展开成逐章计划（依据「卷一开局连战段」+ 各 10 章锚点精神）
GROUPED_021_030 = {
21: ("失联名单", "外采队失联名单在配给署公示栏贴出来，家属围着看，没有人敢先签名认领。", "公示栏前的人潮与保安的对峙，名字被雨水泡花。", "韩星「任务可以重做，人不能重来。」", "把「放弃」变成一件需要有人签字的公开程序——这是本卷第一次把代价推到台面上。"),
22: ("谁给执裁者开的门", "韩星小队被指派追查执裁者的入侵路径，第一条线索指向一扇本该封死的门。", "夜间门禁走廊，封死的门缝里透出光。", "顾南「门是被人从里面打开的。」", "内部问题第一次浮出水面，裴临开始怀疑高层。"),
23: ("失联者还剩几个", "灰市渠道传来外采队残存名单，数字比官方口径少了一半。", "地下配给站的昏黄灯光，情报贩子压低声音报价。", "马有余「你们要的是人，我要的是价钱。」", "灰市成为不可回避的信息来源，也把韩星绑上债。"),
24: ("换防", "界膜防线临时换防，韩星的小队被拆散安插到三个不同区段。", "磁轨摩托穿越城廊，分配命令与身体同时被调度。", "陆策「我们这队是编制，还是消耗品？」", "群体被拆散是本书常用的施压手段：先破坏默契，再谈忠诚。"),
25: ("权限不够", "韩星想调阅更高一级日志，被规则层驳回，理由是「战时权限下放」。", "规则厅的高墙与全息规则链重排，驳回通知逐字滚动。", "林婉儿「你现在能保命，不能查账。」", "把制度写成具体的墙，比写「制度不公」有效得多。"),
26: ("轨道上的接力", "追查线索指向一条废弃输能轨道，跃迁窗口只剩几分钟。", "高速轨道追击，从车厢顶跳到另一节车厢。", "裴临「别算了，先活！」", "呼应卷零的坠落经验，把恐惧变成肌肉记忆。"),
27: ("二十七号救生舱", "找到一处外采队的救生舱，舱内有人还活着，但舱体被矿压卡死。", "狭窄舱内的破拆，三个人轮流顶住变形舱门。", "苏芷「你先出来，他还有气。」", "救谁先救谁——本书第一次把这个选择交给主角，且必须有人死。"),
28: ("矿压爆燃", "破拆引发矿压爆燃，整个平台区连锁塌陷。", "纵向百米坠落追杀，火浪顺着通风井倒灌。", "韩星「这次别一个人冲。」", "代价：救生舱里只出来一个人。"),
29: ("名字写错了", "被救者的身份对不上名册——官方档案里他三年前就死了。", "档案库的全息名册，红色标记一行行亮起。", "季扫尘「死人不需要抚恤，所以最安全。」", "揭示：系统里的假死亡比真死亡更省资源。这是全书伦理崩塌的第一块砖。"),
30: ("卷零余波·谁在接管", "韩星用自身权限做反向诱饵夺回控制链，天幕裂开细长白缝。", "全域警报同频共振，白缝从穹顶一侧缓慢张开。", "祁夜「它不是来进攻，它来接管。」", "卷一开局段收束：把「敌人」从战争行为重新定义为管理行为。"),
}


def parse_blocks(text: str) -> dict[int, str]:
    """从大纲里抠出 ### 000 … ### 020 块。"""
    sec = text.split("## 四、0-30章逐章细纲", 1)
    if len(sec) < 2:
        raise SystemExit("大纲里找不到「四、0-30章逐章细纲」一节")
    body = sec[1].split("## 五、", 1)[0]
    blocks: dict[int, str] = {}
    matches = list(re.finditer(r"^###\s+(\d{3})\s*$", body, re.M))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        blocks[int(m.group(1))] = body[m.end() : end].strip()
    return blocks


def render(kno: int, fno: int, content: str) -> str:
    head = "# 第 %d 章细化大纲\n\n（对应原文件 docs/%03d，内核章节号 %d）\n\n" % (kno, fno, kno)
    return head + content.strip() + "\n"


def render_grouped(fno: int) -> str:
    name, plot, scene, line, motive = GROUPED_021_030[fno]
    kno = fno + KERNEL_OFFSET
    return (
        "# 第 %d 章细化大纲\n\n（对应原文件 docs/%03d，内核章节号 %d；"
        "原大纲只有卷一开局连战段合并描述，此处为按段内推进展开）\n\n"
        "- 章名：《%s》\n- 剧情：%s\n- 场面：%s\n- 台词锚点：%s\n- 动机推进：%s\n"
        % (kno, fno, kno, name, plot, scene, line, motive)
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    text = OUTLINE.read_text(encoding="utf-8")
    blocks = parse_blocks(text)
    print(f"从大纲解析到 {len(blocks)} 个逐章块：{sorted(blocks)[:3]} … {sorted(blocks)[-3:]}")

    PLANS.mkdir(parents=True, exist_ok=True)
    written = 0
    for fno, content in sorted(blocks.items()):
        if fno > 20:
            continue
        dest = PLANS / f"{fno + KERNEL_OFFSET:04d}.md"
        if args.dry_run:
            print(f"  [dry] {dest.name} ← docs/{fno:03d} ({len(content)} 字)")
            continue
        dest.write_text(render(fno + KERNEL_OFFSET, fno, content), encoding="utf-8")
        written += 1

    for fno in GROUPED_021_030:
        dest = PLANS / f"{fno + KERNEL_OFFSET:04d}.md"
        if args.dry_run:
            print(f"  [dry] {dest.name} ← 展开自卷一开局连战段")
            continue
        dest.write_text(render_grouped(fno), encoding="utf-8")
        written += 1

    print(f"✓ 写入 {written} 份 chapter_plans（0001.md–{written:04d}.md）")
    if not args.dry_run:
        print(f"  仍缺：0022.md–0421.md 共 {421 - written} 章，需 batch_generate_chapter_plans 生成")


if __name__ == "__main__":
    sys.exit(main())