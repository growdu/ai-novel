"""Token 成本估算 + 预算跟踪。

支持的模型价格（per 1M tokens，输入/输出分开）：
  - minimax-M3 / Text-01     : ¥1.0 / ¥1.0（minimax 估算）
  - gpt-4o / 4-turbo        : $2.5 / $10
  - deepseek-chat / qwen     : ¥1.0 / ¥1.0（同类估算）
  - claude-3-sonnet         : $3 / $15

如果不知道模型，按 ¥1.0 / 1M token 估算（最保守）。

币种：
- 价格原表单位是 CNY/USD 混合
- 当前默认人民币汇率 1 USD ≈ ¥7.2
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# USD → CNY（覆盖项目周期即可）
USD_TO_CNY = 7.2


# 模型单价表（CNY / 1M tokens）。键是 model 名称前缀（小写）。
MODEL_PRICES_CNY_PER_1M: dict[str, tuple[float, float]] = {
    # (input_price, output_price) 都是人民币 per 1M tokens
    "minimax-": (1.0, 1.0),
    "gpt-4o": (18.0, 72.0),
    "gpt-4-turbo": (18.0, 72.0),
    "gpt-4": (216.0, 432.0),
    "gpt-3.5": (3.6, 7.2),
    "deepseek": (1.0, 2.0),
    "qwen": (4.0, 12.0),
    "glm": (4.0, 12.0),
    "claude-3-5-sonnet": (21.6, 108.0),
    "claude-3-sonnet": (21.6, 108.0),
    "claude-3-opus": (108.0, 540.0),
}


def price_for_model(model: str) -> tuple[float, float]:
    """返回 (input_cny_per_1m, output_cny_per_1m)。未匹配返回保守默认。"""
    if not model:
        return (1.0, 1.0)
    lower = model.lower()
    # 先按精确 key 匹配
    for prefix, prices in MODEL_PRICES_CNY_PER_1M.items():
        if lower.startswith(prefix):
            return prices
    # 兜底：保守估算 ¥1/1M
    return (1.0, 1.0)


def estimate_cost_cny(prompt_tokens: int, completion_tokens: int, model: str = "") -> float:
    """估算一次 LLM 调用的成本（CNY）。"""
    in_price, out_price = price_for_model(model)
    cost = (prompt_tokens / 1_000_000) * in_price + (completion_tokens / 1_000_000) * out_price
    return round(cost, 6)


@dataclass
class BudgetTracker:
    """累加 token / 估算成本；支持预算上限检查。"""

    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_cny: float = 0.0
    budget_cny: float = 0.0
    auto_downgrade_threshold: float = 0.30  # 剩余 < 30% 时降级
    history: list[dict] = field(default_factory=list)  # 每次 add 的快照

    def add(self, prompt_tokens: int, completion_tokens: int) -> float:
        """累加一次 LLM 调用的 token，返回本次成本（CNY）。"""
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        cost = estimate_cost_cny(prompt_tokens, completion_tokens, self.model)
        self.cost_cny += cost
        self.history.append({
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "cost": cost,
        })
        return cost

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def remaining_cny(self) -> float:
        if self.budget_cny <= 0:
            return float("inf")
        return max(0.0, self.budget_cny - self.cost_cny)

    @property
    def ratio_remaining(self) -> float:
        """剩余预算占比。0 = 用完，1 = 未动。"""
        if self.budget_cny <= 0:
            return 1.0
        return self.remaining_cny / self.budget_cny

    def exceeded(self) -> bool:
        return self.budget_cny > 0 and self.cost_cny >= self.budget_cny

    def should_downgrade(self) -> bool:
        """剩余预算比例低于阈值时应降级。"""
        if self.budget_cny <= 0:
            return False
        return self.ratio_remaining < self.auto_downgrade_threshold

    def suggest_quality(self, current_quality: str) -> str:
        """根据剩余预算建议降级后的质量档。"""
        if self.budget_cny <= 0:
            return current_quality
        if self.ratio_remaining < 0.30:
            return "draft"
        if self.ratio_remaining < 0.60:
            return "standard"
        return current_quality

    def summary(self) -> str:
        """格式化一行摘要（CLI / Web 用）。"""
        if self.budget_cny > 0:
            return (
                f"token {self.total_tokens:,} | "
                f"¥{self.cost_cny:.3f} / ¥{self.budget_cny:.2f} "
                f"({self.ratio_remaining*100:.0f}% remaining)"
            )
        return f"token {self.total_tokens:,} | ¥{self.cost_cny:.3f}"