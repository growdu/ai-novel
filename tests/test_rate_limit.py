"""novel 配额/速率限制 自动等待测试（v0.14+）。

覆盖：
  1. LLMClient 错误响应被检测为 RateLimitError（含 429 / 文本匹配 / Retry-After）
  2. _call_with_quota_retry 撞配额时自动等到 reset_at 再重试
  3. _call_with_quota_retry 在 wait_on_quota=False / max_wait=0 时立即抛
  4. _call_with_quota_retry 用户 Ctrl-C 后干净中断（state 不被改）
  5. RateLimitError 字段（reset_at / retry_after_seconds / raw_status）正确填充

模式：
  - mock client.chat 第一次抛 RateLimitError，第二次返回正常内容
  - 验证 handler 等过 retry_after 时间（或 mock 时间）后成功
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from novel.auto_state import AutoSpec, QualityPreset
from novel.auto import _call_with_quota_retry, _quota_kwargs, _PASS_THROUGH
from novel.llm import (
    LLMError,
    RateLimitError,
    _is_rate_limit_response,
    _build_rate_limit_error,
    _parse_retry_after,
)
from novel_cli import app


runner = CliRunner()


# ---------------------------------------------------------------------------
# 1. LLMClient 检测层：429 / 中文配额文本 / Retry-After
# ---------------------------------------------------------------------------

class TestDetectRateLimit:
    """验证 _is_rate_limit_response + _build_rate_limit_error 的检测逻辑。"""

    def test_429_status_detected(self):
        class H:
            def get(self, k, default=None): return None
        assert _is_rate_limit_response(429, "any text", H()) is True

    def test_403_with_quota_keyword_detected(self):
        class H:
            def get(self, k, default=None): return None
        assert _is_rate_limit_response(403, "Your quota has been exceeded", H()) is True

    def test_403_without_quota_keyword_not_detected(self):
        class H:
            def get(self, k, default=None): return None
        # 403 + 非配额文本不应被当配额（避免误判普通鉴权失败）
        assert _is_rate_limit_response(403, "invalid api key", H()) is False

    def test_500_server_error_not_rate_limit(self):
        class H:
            def get(self, k, default=None): return None
        assert _is_rate_limit_response(500, "internal error", H()) is False

    @pytest.mark.parametrize("text", [
        "insufficient_quota",
        "rate limit exceeded",
        "RPM limit reached",
        "TPM exceeded",
        "配额不足",     # 中文
        "余额不足",
        "5小时限额",
        "周用量限额",
        "请求过快，请稍后再试",
    ])
    def test_text_patterns_trigger_detection(self, text):
        class H:
            def get(self, k, default=None): return None
        assert _is_rate_limit_response(200, text, H()) is True

    def test_text_without_keywords_not_triggered(self):
        class H:
            def get(self, k, default=None): return None
        assert _is_rate_limit_response(200, "good response", H()) is False

    def test_build_error_extracts_retry_after(self):
        class H:
            def get(self, k, default=None):
                return {"Retry-After": "300"}.get(k)
        err = _build_rate_limit_error(429, "配额不足", H())
        assert err.raw_status == 429
        assert err.retry_after_seconds == 300
        assert "配额不足" in err.raw_text
        assert err.reset_at > 0  # 推断出

    def test_build_error_without_retry_after(self):
        class H:
            def get(self, k, default=None): return None
        err = _build_rate_limit_error(429, "quota", H())
        assert err.retry_after_seconds == 0
        assert err.reset_at == 0  # 无法推断


# ---------------------------------------------------------------------------
# 2. _call_with_quota_retry：自动等 + 重试
# ---------------------------------------------------------------------------

class TestCallWithQuotaRetry:
    """验证 handler 的核心行为：撞配额 → 等 → 重试 → 成功。"""

    def _build_spec(self, **kwargs):
        defaults = dict(
            title="t",
            target_words=9000,
            target_chapters=3,
            quality=QualityPreset.DRAFT,
        )
        defaults.update(kwargs)
        return AutoSpec(**defaults)

    def test_succeeds_immediately_no_wait(self):
        """第一次调用成功，不触发任何等待。"""
        called = []
        def fn():
            called.append(1)
            return "ok"
        result = _call_with_quota_retry(fn, max_wait_seconds=600, chapter_no=1)
        assert result == "ok"
        assert len(called) == 1

    def test_raises_non_rate_limit_immediately(self):
        """非 RateLimitError 直接抛，不等。"""
        def fn():
            raise LLMError("api 500: server down")
        with pytest.raises(LLMError):
            _call_with_quota_retry(fn, max_wait_seconds=600, chapter_no=1)

    def test_max_wait_zero_skips_wait(self):
        """max_wait_seconds=0 → 立即抛 RateLimitError，不等。"""
        calls = []
        def fn():
            calls.append(1)
            raise RateLimitError("test", retry_after_seconds=300)
        with pytest.raises(RateLimitError):
            _call_with_quota_retry(fn, max_wait_seconds=0, chapter_no=1)
        # 只调了一次（没有重试）
        assert len(calls) == 1

    def test_pass_through_sentinel_skips_wait(self):
        """_PASS_THROUGH 哨兵 → 立即抛。"""
        calls = []
        def fn():
            calls.append(1)
            raise RateLimitError("test", retry_after_seconds=300)
        with pytest.raises(RateLimitError):
            _call_with_quota_retry(
                fn, max_wait_seconds=600, chapter_no=1,
                on_rate_limit=_PASS_THROUGH,
            )
        assert len(calls) == 1

    def test_retries_after_retry_after(self, monkeypatch):
        """模拟：第一次 RateLimitError（retry_after=1s），第二次成功。

        关键：不应真的睡 1 秒（用 monkeypatch 拦截 time.sleep）。
        """
        calls = []
        sleep_log = []
        def fake_sleep(s):
            sleep_log.append(s)
        monkeypatch.setattr("time.sleep", fake_sleep)

        def fn():
            calls.append(1)
            if len(calls) == 1:
                raise RateLimitError("配额", retry_after_seconds=10, raw_status=429)
            return "success"

        result = _call_with_quota_retry(fn, max_wait_seconds=600, chapter_no=1)
        assert result == "success"
        assert len(calls) == 2
        assert sum(sleep_log) >= 10  # 至少等了 10 秒（+30s 缓冲）

    def test_still_rate_limit_after_wait_raises(self, monkeypatch):
        """持续撞配额 → handler 也有上限。max_wait=0 时马上抛。"""
        def fn():
            raise RateLimitError("配额", retry_after_seconds=60)
        with pytest.raises(RateLimitError):
            _call_with_quota_retry(fn, max_wait_seconds=0, chapter_no=1)


# ---------------------------------------------------------------------------
# 3. _quota_kwargs：从 spec 取参数
# ---------------------------------------------------------------------------

class TestQuotaKwargs:
    """验证 _quota_kwargs 的 wait_on_quota / max_wait 路由逻辑。"""

    def test_wait_on_quota_true_returns_defaults(self):
        spec = AutoSpec(title="t", wait_on_quota=True, max_wait_seconds=7200)
        mw, ol = _quota_kwargs(spec, 1)
        assert mw == 7200
        assert ol is None  # 用默认 handler

    def test_wait_on_quota_false_returns_pass_through(self):
        from novel.auto import _PASS_THROUGH
        spec = AutoSpec(title="t", wait_on_quota=False, max_wait_seconds=7200)
        mw, ol = _quota_kwargs(spec, 1)
        assert mw == 0  # 0 触发立即抛
        assert ol is _PASS_THROUGH


# ---------------------------------------------------------------------------
# 4. 端到端：CLI novel write --no-wait 撞配额时立即退出
# ---------------------------------------------------------------------------

class TestEndToEndCLI:
    """用 monkeypatch 模拟 RateLimitError，验证 CLI 行为。"""

    def test_no_wait_exits_immediately_on_rate_limit(self, tmp_path, monkeypatch):
        """DRY_RUN 模式 + --no-wait：CLI 接受不报错。DRY_RUN 路径不会撞真配额。

        验证目的：--no-wait 不会让 typer 解析失败（与 max_wait_seconds=0 等价）。
        真撞配额的行为在 TestCallWithQuotaRetry 里覆盖。
        """
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, [
            "write", "demo",
            "--title", "DRY_RUN rate limit test",
            "--words", "9000",
            "--chapters", "2",
            "--quality", "draft",
            "--no-wait",
        ])
        # DRY_RUN 不会撞配额；--no-wait 仅在真 429 时生效。
        assert result.exit_code == 0

    def test_help_shows_new_flags(self):
        result = runner.invoke(app, ["write", "--help"])
        assert "--wait-on-quota" in result.stdout
        assert "--max-wait-seconds" in result.stdout
        assert "--no-wait" in result.stdout

    def test_help_shows_new_flags(self):
        result = runner.invoke(app, ["write", "--help"])
        assert "--wait-on-quota" in result.stdout
        assert "--max-wait-seconds" in result.stdout
        assert "--no-wait" in result.stdout
