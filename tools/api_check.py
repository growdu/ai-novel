"""API 连通性自检：跑长任务前花几毛钱确认 key / base_url / model 都通。

用法：python3 tools/api_check.py
不打印密钥本身，只打印脱敏信息。
"""
from __future__ import annotations

import sys

from novel.config import load_global
from novel.llm import LLMClient


def main() -> int:
    cfg = load_global()
    print(f"base_url : {cfg.base_url}")
    print(f"model    : {cfg.model}")
    print(f"dry_run  : {cfg.dry_run}")
    key = getattr(cfg, "api_key", "") or ""
    if key:
        print(f"api_key  : {key[:6]}***{key[-4:]}  (长度 {len(key)})")
    else:
        print("api_key  : (空)")
    if cfg.dry_run:
        print("\n⚠️  DRY_RUN=True —— 不会真正调用 API。先去 .env 改成 False。")
        return 2
    if not key or key.startswith("your"):
        print("\n❌ api_key 还是占位符。去 .env 填真实 key，或跑 `novel setup`。")
        return 2

    print("\n发起测试调用……")
    try:
        r = LLMClient(cfg).chat_with_continuation(
            [{"role": "system", "content": "只回复两个字，不要任何解释。"},
             {"role": "user", "content": "回复：连通"}],
            target_words=10, max_total_tokens=200, temperature=0.1,
        )
    except Exception as exc:
        print(f"❌ 调用失败：{type(exc).__name__}: {str(exc)[:300]}")
        print("   常见原因：key 无效 / base_url 不匹配 / 模型名不存在 / 欠费")
        return 1

    print(f"✅ 连通 | {r.model} | {r.elapsed_ms} ms | {r.total_tokens} tokens")
    print(f"   输出: {(r.content or '')[:80]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())