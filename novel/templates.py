"""项目模板库。

10 个预设模板，每个包含：
- name: 模板名（中文）
- description: 风格描述
- genre: 题材
- style: 文风
- default_words: 默认目标字数
- sample_title: 示例标题（可覆盖）
- sample_theme: 示例主题
- sample_characters: 人物设定草稿（可选）

用法：
    from novel.templates import get_template, list_templates
    t = get_template("东北悬疑")
    t = get_template("东北")  # 模糊匹配
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Template:
    """项目模板。"""
    name: str
    description: str
    genre: str
    style: str
    default_words: int
    sample_title: str = ""
    sample_theme: str = ""
    sample_characters: str = ""
    sample_idea: str = ""
    tags: list[str] = field(default_factory=list)


# 模板目录。顺序：先严肃向（按题材分组），最后网文。
TEMPLATES: list[Template] = [
    Template(
        name="东北悬疑",
        description="致敬双雪涛 / 班宇的北方叙事",
        genre="悬疑", style="冷峻",
        default_words=80000,
        sample_title="盘锦往事",
        sample_theme="1995 年东北小镇命案，三个少年的二十年",
        sample_characters="陈小军 / 霍小军 / 小英",
        tags=["现实", "严肃", "双雪涛"],
    ),
    Template(
        name="硬科幻",
        description="贴近刘慈欣 / 阿西莫夫的扎实感",
        genre="科幻", style="朴素",
        default_words=60000,
        sample_title="三体回响",
        sample_theme="人类文明首次接触外星信号后的 30 年",
        sample_characters="叶文洁 / 汪淼 / 罗辑",
        tags=["科幻", "硬科幻", "刘慈欣"],
    ),
    Template(
        name="古典言情",
        description="致敬张爱玲 / 王安忆的细腻",
        genre="言情", style="诗意",
        default_words=50000,
        sample_title="倾城之恋新编",
        sample_theme="1940 年代上海名门闺秀与穷学生的乱世爱情",
        sample_characters="白流苏 / 范柳原",
        tags=["言情", "民国", "张爱玲"],
    ),
    Template(
        name="武侠经典",
        description="致敬金庸 / 古龙的江湖气",
        genre="武侠", style="朴素",
        default_words=120000,
        sample_title="倚天屠龙新传",
        sample_theme="元末明初，少年张无忌得九阳真经",
        tags=["武侠", "古代", "金庸"],
    ),
    Template(
        name="轻松校园",
        description="日系轻小说 / 国产青春剧",
        genre="校园", style="轻松",
        default_words=30000,
        sample_title="同桌的她",
        sample_theme="高中最后一个学期的暗恋故事",
        sample_characters="林夕 / 苏阳",
        tags=["校园", "青春", "轻小说"],
    ),
    Template(
        name="诗意现实",
        description="致敬汪曾祺 / 沈从文的淡墨",
        genre="现实", style="诗意",
        default_words=40000,
        sample_title="受戒新编",
        sample_theme="江南水乡的童年记忆与少年心事",
        tags=["现实", "乡土", "汪曾祺"],
    ),
    Template(
        name="黑色幽默",
        description="致敬余华 / 王小波的戏谑",
        genre="都市", style="黑色幽默",
        default_words=50000,
        sample_title="黄金时代新编",
        sample_theme="90 年代小城青年的荒诞日常",
        sample_characters="王二 / 姓孙的斗二",
        tags=["都市", "荒诞", "王小波"],
    ),
    Template(
        name="网文经典",
        description="百万字长篇网文",
        genre="修仙", style="经典爽文",
        default_words=2000000,
        sample_title="凡人仙途",
        sample_theme="凡人觉醒逆袭修仙",
        sample_idea="残破玉佩内藏完整《九天神诀》",
        tags=["网文", "修仙", "爽文"],
    ),
    Template(
        name="虐心言情",
        description="情感细腻、有遗憾感",
        genre="言情", style="伤感",
        default_words=40000,
        sample_title="十年后",
        sample_theme="分手十年后的重逢，看清彼此的生活",
        tags=["言情", "伤感", "重逢"],
    ),
    Template(
        name="紧张悬疑",
        description="节奏快、悬念密",
        genre="悬疑", style="紧张",
        default_words=60000,
        sample_title="无人生还",
        sample_theme="孤岛别墅，十个陌生人，凶手就在其中",
        sample_characters="十个陌生人 / 一个侦探",
        tags=["悬疑", "推理", "暴风雪山庄"],
    ),
]


def list_templates() -> list[Template]:
    """返回所有模板。"""
    return list(TEMPLATES)


def get_template(query: str) -> Optional[Template]:
    """根据查询字符串返回匹配的模板（None 表示未找到）。

    匹配规则：
    1. 完全匹配 name
    2. 包含关系（query in t.name 或 t 在 query）
    3. tag 命中
    """
    if not query:
        return None
    # 1. 精确
    for t in TEMPLATES:
        if t.name == query:
            return t
    # 2. 包含
    for t in TEMPLATES:
        if query in t.name or t.name in query:
            return t
    # 3. tag
    for t in TEMPLATES:
        if query in t.tags:
            return t
    # 4. description 包含
    for t in TEMPLATES:
        if query in t.description:
            return t
    return None


def apply_template(template: Template, overrides: dict | None = None) -> dict:
    """把模板转成 init 参数（dict 格式）。可被 overrides 覆盖。

    overrides 中值为 None 的字段视为未指定，使用模板默认值。
    返回字段：title, theme, genre, style, words, characters, idea
    """
    # 过滤掉 None：dict.get(key, default) 只在 key 缺失时才返回 default，
    # 若 key 存在但值是 None，仍返回 None（会让用户指定字段失效）。
    clean_overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    return {
        "title": clean_overrides.get("title", template.sample_title),
        "theme": clean_overrides.get("theme", template.sample_theme),
        "genre": clean_overrides.get("genre", template.genre),
        "style": clean_overrides.get("style", template.style),
        "words": clean_overrides.get("words", template.default_words),
        "characters": clean_overrides.get("characters", template.sample_characters),
        "idea": clean_overrides.get("idea", template.sample_idea),
    }