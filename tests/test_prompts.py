"""novel.prompts 单元测试。

覆盖：题材/文风预设匹配、消息构建、缓存命中。
"""
from __future__ import annotations

from novel import prompts as P


class TestPresetListing:
    """题材与文风列表：精确 / 模糊匹配。"""

    def test_list_genres_returns_at_least_10(self):
        genres = P.list_genres()
        assert len(genres) >= 10
        # 不应包含分类标题
        assert "题材硬规则与常见设定" not in genres
        assert "文风预设" not in genres

    def test_list_styles_returns_at_least_10(self):
        styles = P.list_styles()
        assert len(styles) >= 10
        assert "文风预设" not in styles

    def test_list_webnovel_genres(self):
        web_genres = P.list_webnovel_genres()
        # 实际网文题材 8 个（README 写过 9，已更新）
        assert len(web_genres) >= 7
        assert "通用网文节奏" not in web_genres

    def test_list_webnovel_styles(self):
        web_styles = P.list_webnovel_styles()
        # 实际爽感文风 9 个
        assert len(web_styles) >= 8


class TestPresetMatching:
    """模糊匹配：精确 / 包含 / 前缀。"""

    def test_get_genre_block_exact(self):
        # 用 list_genres()[0] 测试
        first = P.list_genres()[0]
        block = P.get_genre_block(first)
        assert first in block

    def test_get_genre_block_partial_match(self):
        # 输入 "悬疑" 应该匹配到完整标题
        block = P.get_genre_block("悬疑")
        # 可能精确匹配"悬疑"，也可能模糊匹配——只要返回非空即可
        if P.list_genres():
            # 至少匹配到包含"悬疑"的项
            matched = next((g for g in P.list_genres() if "悬疑" in g), None)
            if matched:
                assert matched in block

    def test_get_genre_block_unknown_returns_empty(self):
        assert P.get_genre_block("根本不存在的题材XYZ") == ""

    def test_get_style_block_exact(self):
        if P.list_styles():
            first = P.list_styles()[0]
            block = P.get_style_block(first)
            assert first in block

    def test_get_style_block_unknown(self):
        assert P.get_style_block("zzz未知文风") == ""

    def test_get_webnovel_genre_block(self):
        if P.list_webnovel_genres():
            first = P.list_webnovel_genres()[0]
            block = P.get_webnovel_genre_block(first)
            assert first in block

    def test_get_webnovel_style_block(self):
        if P.list_webnovel_styles():
            first = P.list_webnovel_styles()[0]
            block = P.get_webnovel_style_block(first)
            assert first in block

    def test_empty_input_returns_empty(self):
        assert P.get_genre_block("") == ""
        assert P.get_style_block("") == ""
        assert P.get_webnovel_genre_block("") == ""
        assert P.get_webnovel_style_block("") == ""


class TestMessageBuilders:
    """所有 build_xxx_messages 返回 Message 列表。"""

    def test_build_chapter_messages_has_system_and_user(self):
        ctx = P.ChapterContext(
            title="测试",
            outline="大纲",
            characters="人物",
            style="文风",
            chapter_plan="本章规划",
            prev_chapter_tail="上文",
            target_words=3000,
        )
        msgs = P.build_chapter_messages(ctx)
        assert len(msgs) == 2
        assert msgs[0].role == "system"
        assert msgs[1].role == "user"
        assert "去 AI 味" in msgs[0].content or "AI 味" in msgs[0].content
        assert "测试" in msgs[1].content
        assert "3000" in msgs[1].content

    def test_build_chapter_messages_with_feedback(self):
        ctx = P.ChapterContext(
            title="x", outline="", characters="", style="",
            chapter_plan="", prev_chapter_tail="", target_words=3000,
            feedback="必须加强对话戏"
        )
        msgs = P.build_chapter_messages(ctx)
        assert "加强对话戏" in msgs[1].content

    def test_build_chapter_messages_with_extra(self):
        ctx = P.ChapterContext(
            title="x", outline="", characters="", style="",
            chapter_plan="", prev_chapter_tail="", target_words=3000,
            extra="加一段回忆杀"
        )
        msgs = P.build_chapter_messages(ctx)
        assert "回忆杀" in msgs[1].content

    def test_build_outline_messages_includes_genre_block(self):
        # 输入一个真实存在的题材
        if P.list_genres():
            g = P.list_genres()[0]
            msgs = P.build_outline_messages("测试", "主题", g, 50000, "", "")
            assert len(msgs) == 2
            assert g in msgs[0].content  # 题材硬规则应被注入 system

    def test_build_detect_messages(self):
        msgs = P.build_detect_messages("待检测内容")
        assert len(msgs) == 2
        assert "待检测内容" in msgs[1].content

    def test_build_polish_messages_with_detect_report(self):
        msgs = P.build_polish_messages(
            content="原文",
            chapter_plan="本人章",
            prev_tail="上一章结尾",
            detect_report="检测报告",
            extra=""
        )
        assert len(msgs) == 2
        assert "检测报告" in msgs[1].content

    def test_build_skeleton_messages(self):
        msgs = P.build_skeleton_messages("源小说信息...")
        assert len(msgs) == 2
        assert "源小说信息" in msgs[1].content

    def test_build_adapt_messages_with_genre_style(self):
        g = P.list_genres()[0] if P.list_genres() else ""
        s = P.list_styles()[0] if P.list_styles() else ""
        msgs = P.build_adapt_messages("源", "", "换名", g, s)
        assert len(msgs) == 2


class TestPromptCaching:
    """@lru_cache(maxsize=1) 让重复调用只读一次磁盘。"""

    def test_repeated_load_returns_same_object(self):
        # 由于 maxsize=1，多次调用应返回同一对象
        a = P.de_ai_flavour()
        b = P.de_ai_flavour()
        assert a is b

    def test_all_prompts_loadable(self):
        """所有提示词文件应能加载。"""
        names = [
            "de_ai_flavour", "outline", "character", "chapter",
            "detect_ai", "polish", "review", "state", "world",
            "timeline", "foreshadow", "volume", "arc", "consistency",
            "samples", "volume_report", "genre_presets", "style_presets",
            "adapt", "fanfic", "skeleton", "webnovel_genres", "webnovel_style",
            "rolling_summary", "chapter_title", "style_radar", "expand_scene",
            "continue_chapter", "chat_assistant", "chapter_plan",
        ]
        for name in names:
            text = getattr(P, name)()
            assert isinstance(text, str)
            assert len(text) > 50, f"{name} 内容过短"