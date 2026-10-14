"""novel.llm 单元测试。

重点覆盖 _strip_think_tags 三层兜底：minimax-M3 推理模型的关键路径。
"""
from __future__ import annotations

import pytest

from novel.llm import (
    LLMClient,
    LLMResult,
    Message,
    _strip_think_tags,
    _try_parse_json,
)


class TestStripThinkTags:
    """三层兜底：闭合 → 部分闭合 → 任何含 <think> → 英文 think 残片。"""

    def test_empty(self):
        assert _strip_think_tags("") == ""
        assert _strip_think_tags(None) is None

    def test_clean_text_unchanged(self):
        # 函数末尾会做 .strip()，所以原样保留意味着结尾不能有空白
        text = "正文开始。\n第一章\n我从床上爬起来。"
        assert _strip_think_tags(text) == text

    def test_clean_text_strips_trailing_whitespace(self):
        # 末尾空白会被 .strip() 去掉——这是 by design
        text = "正文\n"
        assert _strip_think_tags(text) == "正文"

    def test_closed_think_block_removed(self):
        text = "<think>用户在问什么</think>\n\n## 第一章\n\n我从床上爬起来。"
        out = _strip_think_tags(text)
        assert "<think>" not in out
        assert "## 第一章" in out
        assert "我从床上爬起来" in out

    def test_partial_think_with_adjacent_heading(self):
        """未闭合的 think 块，跟着标题 → 截到标题开始。"""
        text = "<think>用户在问：\n- 主题\n- 设定\n\n## 第一章 冬夜\n\n他从雪里爬起来。"
        out = _strip_think_tags(text)
        assert "## 第一章" in out
        assert "他从雪里爬起来" in out
        # think 残片应被截掉
        assert "- 主题" not in out

    def test_any_think_keyword_truncates(self):
        """无闭合 <think> + 无 \n\n 边界：partial regex 兜底从 eat 边界一直吃到末尾。"""
        # 没有 \n\n 边界的 think 块：partial regex 用 \Z 兜底，整个 think+残余被剥
        text = "前面是干净的。<think>等等让我想后面紧跟没有空行"
        out = _strip_think_tags(text)
        assert "前面是干净的。" in out
        assert "等等让我想" not in out
        assert "后面紧跟" not in out

    def test_third_layer_kicks_in_for_stray_token(self):
        """第三层兜底：之前两步都没剥掉的独立 <think> 标签会从该处截断。"""
        # 构造一个 partial regex 也无法处理的场景：
        # 让 partial regex 因为 \Z 边界匹配 " 直至末尾"（已剥尽），
        # 然后在 text 后面再注入一个 <think> 模拟残留 token。
        # 实际生产中这部分罕见，主要测函数不会无限循环
        text = "正常段落\n<think>稍后内容被剥离\n更多内容。\n\n## 标题\n\n正文开始。"
        out = _strip_think_tags(text)
        assert "正常段落" in out
        assert "稍后内容" not in out
        assert "## 标题" in out
        assert "正文开始" in out

    def test_english_think_residue_with_heading(self):
        """开头 15 行内出现英文 think 残片 + markdown 标题 → 从首个标题截断。"""
        text = (
            "OK so I should not have a think block but here we go\n"
            "Let me think about what the user wants\n"
            "The user wants a chapter about winter\n"
            "So I'll start with the character waking up\n"
            "\n"
            "## 第一章 冬晨\n"
            "\n"
            "我从床上爬起来。"
        )
        out = _strip_think_tags(text)
        # 开头英文 think 残片应被去掉
        assert "OK so I should" not in out
        assert "## 第一章 冬晨" in out
        assert "我从床上爬起来" in out

    def test_no_heading_keeps_english_intact(self):
        """如果 15 行内没标题，英文 think 残片应保留（不影响正文）。"""
        text = "OK so let me start writing\n正文"
        out = _strip_think_tags(text)
        assert "OK so" in out
        assert "正文" in out


class TestTryParseJson:
    """_try_parse_json 兼容 think 残片、纯 JSON、JSON-in-codeblock。"""

    def test_pure_json(self):
        out = _try_parse_json('{"a": 1, "b": 2}')
        assert out == {"a": 1, "b": 2}

    def test_json_in_codeblock(self):
        text = "```json\n{\"x\": 3}\n```"
        out = _try_parse_json(text)
        assert out == {"x": 3}

    def test_json_with_think_residue(self):
        text = "<think>thinking</think>```json\n{\"y\": 4}\n```"
        out = _try_parse_json(text)
        assert out == {"y": 4}

    def test_invalid_json_falls_back_to_raw(self):
        text = "not json at all"
        out = _try_parse_json(text)
        assert "_raw" in out
        assert out["_error"] == "json parse failed"


class TestMessageDataclass:
    def test_to_dict_shape(self):
        m = Message("user", "hello")
        assert m.to_dict() == {"role": "user", "content": "hello"}

    def test_round_trip(self):
        m = Message("assistant", "你好")
        d = m.to_dict()
        assert d["content"] == "你好"
        assert d["role"] == "assistant"


class TestLLMClientDryRun:
    """DRY_RUN 模式不调 API，返回占位内容。"""

    def test_dry_run_returns_placeholder(self, monkeypatch, capsys):
        from novel.config import GlobalConfig

        cfg = GlobalConfig()
        cfg.dry_run = True
        client = LLMClient(cfg)
        res = client.chat([Message("user", "你好")])
        assert isinstance(res, LLMResult)
        assert "[DRY_RUN" in res.content
        # prompt 应被打印到 stdout
        captured = capsys.readouterr()
        assert "DRY_RUN" in captured.out

    def test_dry_run_stream_yields_snippet(self):
        from novel.config import GlobalConfig

        cfg = GlobalConfig()
        cfg.dry_run = True
        client = LLMClient(cfg)
        msgs = [Message("user", "test content")]
        chunks = list(client.stream_chat(msgs))
        assert len(chunks) == 1
        assert "DRY_RUN" in chunks[0]


class TestLLMResultDataclass:
    def test_default_field(self):
        r = LLMResult(content="hi")
        assert r.model == ""
        assert r.prompt_tokens == 0
        assert r.total_tokens == 0
        assert r.raw == {}
        assert r.elapsed_ms == 0


@pytest.mark.parametrize(
    "text,expected_substr",
    [
        ("<think>thinking</think>干净", "干净"),
        ("## 标题\n正文", "## 标题"),
    ],
)
def test_strip_think_tags_idempotency(text, expected_substr):
    """重复调用应稳定：剥完 think 后再剥一次不变。"""
    once = _strip_think_tags(text)
    twice = _strip_think_tags(once)
    assert once == twice
    assert expected_substr in once