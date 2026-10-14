"""novel.budget + novel.token_tracker 单元测试。"""
from __future__ import annotations

from dataclasses import dataclass

from novel.budget import (
    BudgetTracker,
    MODEL_PRICES_CNY_PER_1M,
    estimate_cost_cny,
    price_for_model,
)
from novel.llm import LLMResult, Message
from novel.token_tracker import TokenTracker


class TestPriceForModel:
    def test_minimax_default(self):
        in_p, out_p = price_for_model("minimax-Text-01")
        assert (in_p, out_p) == (1.0, 1.0)

    def test_gpt4o(self):
        in_p, out_p = price_for_model("gpt-4o")
        assert in_p > 0 and out_p > in_p  # output 永远比 input 贵

    def test_deepseek(self):
        in_p, out_p = price_for_model("deepseek-chat")
        assert (in_p, out_p) == (1.0, 2.0)

    def test_unknown_model_returns_conservative(self):
        in_p, out_p = price_for_model("totally-unknown-model-xyz")
        assert in_p == 1.0
        assert out_p == 1.0

    def test_empty_string_returns_conservative(self):
        assert price_for_model("") == (1.0, 1.0)


class TestEstimateCost:
    def test_zero_tokens(self):
        assert estimate_cost_cny(0, 0, "minimax-Text-01") == 0.0

    def test_minimax_1m_input(self):
        # 1M input tokens × ¥1/1M = ¥1
        cost = estimate_cost_cny(1_000_000, 0, "minimax-Text-01")
        assert cost == pytest_approx(1.0)

    def test_gpt4o_1m_each(self):
        # GPT-4o: input ¥18/1M, output ¥72/1M
        cost = estimate_cost_cny(1_000_000, 1_000_000, "gpt-4o")
        assert cost == pytest_approx(18.0 + 72.0)


from pytest import approx as pytest_approx


class TestBudgetTracker:
    def test_initial_state(self):
        bt = BudgetTracker(model="minimax-Text-01", budget_cny=10.0)
        assert bt.total_tokens == 0
        assert bt.cost_cny == 0.0
        assert bt.exceeded() is False
        assert bt.remaining_cny == 10.0

    def test_add_accumulates(self):
        bt = BudgetTracker(model="minimax-Text-01", budget_cny=10.0)
        bt.add(prompt_tokens=1000, completion_tokens=500)
        assert bt.prompt_tokens == 1000
        assert bt.completion_tokens == 500
        assert bt.total_tokens == 1500
        assert bt.cost_cny > 0

    def test_exceeded(self):
        bt = BudgetTracker(model="minimax-Text-01", budget_cny=0.001)
        bt.add(prompt_tokens=100_000_000, completion_tokens=0)  # 100M = ¥100
        assert bt.exceeded() is True

    def test_no_budget_never_exceeds(self):
        bt = BudgetTracker(model="minimax-Text-01", budget_cny=0)
        bt.add(prompt_tokens=1_000_000_000, completion_tokens=1_000_000_000)
        assert bt.exceeded() is False

    def test_should_downgrade_low_remaining(self):
        bt = BudgetTracker(model="minimax-Text-01", budget_cny=10.0)
        bt.add(prompt_tokens=8_000_000, completion_tokens=0)  # ¥8 used
        assert bt.ratio_remaining == pytest_approx(0.2)
        assert bt.should_downgrade() is True  # < 30%

    def test_should_downgrade_healthy(self):
        bt = BudgetTracker(model="minimax-Text-01", budget_cny=10.0)
        bt.add(prompt_tokens=1_000_000, completion_tokens=0)  # ¥1 used
        assert bt.should_downgrade() is False

    def test_suggest_quality(self):
        bt = BudgetTracker(model="minimax-Text-01", budget_cny=10.0)
        # Used < 30%
        bt.add(prompt_tokens=8_000_000, completion_tokens=0)
        assert bt.suggest_quality("premium") == "draft"
        # Used 40-60%
        bt2 = BudgetTracker(model="minimax-Text-01", budget_cny=10.0)
        bt2.add(prompt_tokens=5_000_000, completion_tokens=0)  # ¥5
        assert bt2.suggest_quality("premium") == "standard"
        # Used > 60% keep current
        bt3 = BudgetTracker(model="minimax-Text-01", budget_cny=10.0)
        bt3.add(prompt_tokens=2_000_000, completion_tokens=0)
        assert bt3.suggest_quality("premium") == "premium"

    def test_summary_no_budget(self):
        bt = BudgetTracker(model="minimax-Text-01")
        bt.add(prompt_tokens=1000, completion_tokens=500)
        s = bt.summary()
        assert "token 1,500" in s
        assert "¥" in s

    def test_summary_with_budget(self):
        bt = BudgetTracker(model="minimax-Text-01", budget_cny=10.0)
        bt.add(prompt_tokens=1_000_000, completion_tokens=0)
        s = bt.summary()
        assert "remaining" in s


class TestTokenTracker:
    @staticmethod
    def _fake_result(prompt: int = 1000, completion: int = 500) -> LLMResult:
        return LLMResult(
            content="x" * completion,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        )

    def test_records_from_chat(self, monkeypatch):
        from novel.config import GlobalConfig
        cfg = GlobalConfig()
        cfg.dry_run = True
        client = LLMClient(cfg)
        tracker = TokenTracker(client, model="minimax-Text-01")

        # mock client.chat to return fixed tokens
        def fake_chat(messages, **kwargs):
            return self._fake_result(1500, 800)
        monkeypatch.setattr(client, "chat", fake_chat)

        result = tracker.chat([Message("user", "hi")])
        assert tracker.prompt_tokens == 1500
        assert tracker.completion_tokens == 800
        assert tracker.call_count == 1
        assert tracker.total_tokens == 2300
        assert result.completion_tokens == 800

    def test_record_method(self):
        from novel.config import GlobalConfig
        cfg = GlobalConfig()
        client = LLMClient(cfg)
        tracker = TokenTracker(client, model="minimax-Text-01")
        tracker.record(100, 50, label="manual")
        assert tracker.prompt_tokens == 100
        assert tracker.completion_tokens == 50
        assert tracker.history[0]["label"] == "manual"

    def test_to_budget_tracker(self):
        from novel.config import GlobalConfig
        cfg = GlobalConfig()
        client = LLMClient(cfg)
        tracker = TokenTracker(client, model="minimax-Text-01")
        tracker.record(1_000_000, 500_000)
        bt = tracker.to_budget_tracker(budget_cny=5.0)
        assert bt.prompt_tokens == 1_000_000
        assert bt.completion_tokens == 500_000
        assert bt.budget_cny == 5.0
        assert bt.cost_cny > 0

    def test_reset_counters(self):
        from novel.config import GlobalConfig
        cfg = GlobalConfig()
        client = LLMClient(cfg)
        tracker = TokenTracker(client, model="minimax-Text-01")
        tracker.record(100, 50)
        tracker.reset_counters()
        assert tracker.prompt_tokens == 0
        assert tracker.completion_tokens == 0
        assert tracker.history == []


# Avoid duplicate import (use approx)
from novel.llm import LLMClient
import pytest