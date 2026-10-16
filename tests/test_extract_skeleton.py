"""novel.generator.extract_skeleton 直接单测（v0.14.x 测试深度补齐）。

之前的覆盖：仅 DRY_RUN 端到端通过 novel write --from-source 间接跑。
目标：mock LLMClient.chat_with_continuation，断言
  - 调用了 build_skeleton_messages（正确的源输入）
  - 用了正确的 target_words / temperature（约定值）
  - 返 LLMResult.content 字符串被原样返回
  - 当 .content 为 None 时返回空字符串（不是 None）
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from novel import generator as G
from novel.llm import LLMResult


class FakeClient:
    """记录每次 chat / chat_with_continuation 调用参数的最小 mock。"""

    def __init__(self, content="骨架内容"):
        self.calls = []
        self._content = content

    def chat(self, messages, **kwargs):
        self.calls.append(("chat", messages, kwargs))
        return LLMResult(content=self._content, model="fake", elapsed_ms=1)

    def chat_with_continuation(self, messages, **kwargs):
        self.calls.append(("chat_with_continuation", messages, kwargs))
        return LLMResult(content=self._content, model="fake", elapsed_ms=1)


class TestExtractSkeleton:
    """extract_skeleton 的直接单测。"""

    def test_returns_llm_content_stripped(self):
        client = FakeClient(content="  第一行\n\n第二行  ")
        result = G.extract_skeleton("某源小说简介", client=client)
        assert result == "第一行\n\n第二行"

    def test_calls_chat_with_continuation(self):
        client = FakeClient()
        G.extract_skeleton("某源小说简介", client=client)
        assert len(client.calls) == 1
        kind, _, _ = client.calls[0]
        assert kind == "chat_with_continuation"

    def test_passes_source_to_build_skeleton(self):
        """确认 extract_skeleton 把源小说简介原样传给 build_skeleton_messages。"""
        client = FakeClient()
        G.extract_skeleton("一段源小说简介", client=client)
        _, msgs, _ = client.calls[0]
        # build_skeleton_messages 接受 source string 并包成 messages list
        assert len(msgs) >= 1
        # 最后一条 user 消息应包含源小说简介
        last_msg = msgs[-1]
        assert "一段源小说简介" in getattr(last_msg, "content", "")

    def test_uses_correct_target_words(self):
        """约定 target_words=600, temperature=0.4（DOC 中说明的「低保真骨架提取」）。"""
        client = FakeClient()
        G.extract_skeleton("x", client=client)
        _, _, kwargs = client.calls[0]
        assert kwargs.get("target_words") == 600
        assert kwargs.get("temperature") == pytest.approx(0.4)

    def test_returns_empty_string_when_content_is_none(self):
        """LLM 偶发返回 content=None 时，extract_skeleton 应返回 "" 而不抛 NoneType。"""

        class NoneClient:
            def chat_with_continuation(self, messages, **kw):
                return LLMResult(content=None, model="fake", elapsed_ms=1)

        result = G.extract_skeleton("x", client=NoneClient())
        assert result == ""

    def test_default_client_is_used_when_none(self):
        """不传 client 时也应能跑（默认 LLMClient 默认 GlobalConfig()。DRY_RUN）"""
        # 默认 client 在 DRY_RUN 模式返回 fixture；这里只验证不抛
        import os
        os.environ["DRY_RUN"] = "true"
        os.environ["OPENAI_API_KEY"] = "test-12345678"
        try:
            result = G.extract_skeleton("x")
            # DRY_RUN 返回固定内容（含"[DRY_RUN]"）
            assert "[DRY_RUN]" in result or len(result) > 0
        finally:
            os.environ.pop("DRY_RUN", None)
