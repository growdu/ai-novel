"""Token 追踪包装器：包 LLMClient 记录 token 用量。

用法：
  client = LLMClient(cfg)
  tracker = TokenTracker(client)
  result = tracker.chat([Message(...)])
  print(tracker.prompt_tokens, tracker.completion_tokens)

这样不需要修改 generator.py 里其他 LLMClient 实例化点，
直接传递 tracker 即可捕获 token。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from novel.budget import BudgetTracker, estimate_cost_cny
from novel.llm import LLMClient, LLMResult, Message


@dataclass
class TokenTracker:
    """包装 LLMClient，每次 chat / chat_with_continuation 调用后累加 token。"""

    client: LLMClient
    prompt_tokens: int = 0
    completion_tokens: int = 0
    call_count: int = 0
    model: str = ""
    history: list[dict] = field(default_factory=list)

    def __post_init__(self):
        # 自动从 client 拿 model
        if not self.model and hasattr(self.client, "cfg"):
            self.model = getattr(self.client.cfg, "model", "")

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def estimated_cost_cny(self) -> float:
        return estimate_cost_cny(self.prompt_tokens, self.completion_tokens, self.model)

    def reset_counters(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.call_count = 0
        self.history = []

    def record(self, prompt: int, completion: int, label: str = "") -> float:
        """手动累加（用于已经从外部拿到 LLMResult 的情况）。"""
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.call_count += 1
        cost = estimate_cost_cny(prompt, completion, self.model)
        self.history.append({
            "label": label,
            "prompt": prompt,
            "completion": completion,
            "cost": cost,
        })
        return cost

    def chat(self, messages, **kwargs) -> LLMResult:
        result = self.client.chat(messages, **kwargs)
        self.record(result.prompt_tokens, result.completion_tokens, label="chat")
        return result

    def chat_with_continuation(self, messages, **kwargs) -> LLMResult:
        result = self.client.chat_with_continuation(messages, **kwargs)
        self.record(result.prompt_tokens, result.completion_tokens, label="continuation")
        return result

    def chat_json(self, messages, **kwargs):
        result = self.client.chat_json(messages, **kwargs)
        # chat_json 内部走 chat，已 record 一次；这里不再重复
        return result

    def stream_chat(self, messages, **kwargs):
        return self.client.stream_chat(messages, **kwargs)

    def to_budget_tracker(self, budget_cny: float = 0.0) -> BudgetTracker:
        """导出成 BudgetTracker（用于超预算检查）。"""
        bt = BudgetTracker(
            model=self.model,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            cost_cny=self.estimated_cost_cny,
            budget_cny=budget_cny,
        )
        bt.history = self.history
        return bt