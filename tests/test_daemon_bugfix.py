"""daemon 运行时缺陷的回归测试（v0.18）。

覆盖本次排查确认的四个真 bug：
  A. LLMClient 没有 token 计数器 → auto.py 的 hasattr 判断恒 False → 成本统计恒 0
  B. _write_one_chapter_locked 构造 ChapterResult 时未传 token/cost 字段
  C. 并发 worker 读 auto_state.ChapterResult.content → 每章抛 AttributeError
  D. 停止机制接错线：daemon stop 写 stop_daemon，章级检查读 auto_control.json
  E. 字数门控失败的 retry 反馈不含可执行的补足指令

写法：先看失败（RED），再改实现（GREEN）。
"""
from __future__ import annotations

import json

import pytest

from novel.config import GlobalConfig
from novel.llm import LLMClient
from novel.quality_gates import GateResult
from novel.web import ControlSignal

# ---------------------------------------------------------------------------
# A. LLMClient token 计数器
# ---------------------------------------------------------------------------

class TestClientTokenCounters:
    """LLMClient 必须暴露累计 token 计数——auto.py 靠它算成本。"""

    def _client(self) -> LLMClient:
        cfg = GlobalConfig(
            base_url="https://example.invalid/v1",
            api_key="test-key-12345678",
            model="test-model",
            dry_run=False,
        )
        return LLMClient(cfg)

    def test_client_exposes_prompt_tokens_attribute(self):
        """auto.py 的 `hasattr(client, "prompt_tokens")` 必须为真。"""
        client = self._client()
        assert hasattr(client, "prompt_tokens")
        assert client.prompt_tokens == 0

    def test_counters_accumulate_across_chat_calls(self, monkeypatch):
        """每次 chat() 成功后应把 usage 累加进计数器。"""
        import novel.llm as llm_mod

        calls = {"n": 0}

        class _Resp:
            status_code = 200
            text = "{}"

            def json(self):
                calls["n"] += 1
                # 每次返回固定 usage，便于累加验证
                return {
                    "model": "test-model",
                    "choices": [{"message": {"content": "正文"}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                }

        monkeypatch.setattr(llm_mod.requests, "post", lambda *a, **k: _Resp())

        client = self._client()
        from novel.llm import Message
        msgs = [Message(role="user", content="hi")]

        client.chat(msgs)
        client.chat(msgs)

        assert client.prompt_tokens == 200
        assert client.completion_tokens == 100
        assert client.total_tokens == 300

    def test_failed_call_does_not_inflate_counters(self, monkeypatch):
        """抛异常时不该累计 token（避免把没花的钱算进去）。"""
        import novel.llm as llm_mod

        def _boom(*a, **k):
            raise llm_mod.requests.RequestException("network down")

        monkeypatch.setattr(llm_mod.requests, "post", _boom)

        client = self._client()
        from novel.llm import Message
        with pytest.raises(llm_mod.LLMError):
            client.chat([Message(role="user", content="hi")], retry=1)

        assert client.total_tokens == 0


# ---------------------------------------------------------------------------
# B. token 增量helper
# ---------------------------------------------------------------------------

class TestTokenDelta:
    """成本按「本章净增」累计，而非快照。"""

    def test_delta_subtracts_snapshot(self):
        from novel.auto import _token_delta

        before = (100, 50, 150)
        after = (250, 130, 380)
        assert _token_delta(before, after) == (150, 80, 230)

    def test_delta_handles_missing_counters(self):
        """client 没计数时按 0 处理，不炸。"""
        from novel.auto import _token_delta

        assert _token_delta((0, 0, 0), (0, 0, 0)) == (0, 0, 0)

    def test_delta_never_negative(self):
        """计数器重置时不产生负 token。"""
        from novel.auto import _token_delta

        assert _token_delta((500, 500, 1000), (10, 10, 20)) == (10, 10, 20)


# ---------------------------------------------------------------------------
# D. 停止机制
# ---------------------------------------------------------------------------

class TestStopSignalWiring:
    """`daemon stop` 写的信号必须被章级循环读到。"""

    def test_stop_writes_signal_chapter_loop_reads(self, tmp_path):
        """老路径只写 stop_daemon，章级检查读 auto_control.json——必须桥接。"""
        from novel.commands._daemon import _write_stop_file

        _write_stop_file(tmp_path)

        assert (tmp_path / ".novel" / "stop_daemon").exists()
        # 关键：章级 _check_control_signal 读的是这个
        assert ControlSignal.read(tmp_path) == ControlSignal.STOP

    def test_chapter_loop_also_honours_stop_daemon(self, tmp_path):
        """即使只写了 stop_daemon（老 CLI / web UI 路径），章级循环也应识别。"""
        from novel.auto import _stop_requested

        (tmp_path / ".novel").mkdir()
        (tmp_path / ".novel" / "stop_daemon").write_text("", encoding="utf-8")

        assert _stop_requested(tmp_path) is True

    def test_no_stop_file_means_not_stopping(self, tmp_path):
        from novel.auto import _stop_requested

        (tmp_path / ".novel").mkdir()
        assert _stop_requested(tmp_path) is False

    def test_run_signal_means_not_stopping(self, tmp_path):
        from novel.auto import _stop_requested

        (tmp_path / ".novel").mkdir()
        ControlSignal.write(tmp_path, ControlSignal.RUN)
        assert _stop_requested(tmp_path) is False


# ---------------------------------------------------------------------------
# E. 字数门控 retry 反馈
# ---------------------------------------------------------------------------

class TestWordCountRetryFeedback:
    """反馈必须可执行：说清差多少字、怎么补。"""

    def _failed_word_gate(self) -> list[GateResult]:
        # payload 与 check_word_count 实际产出保持一致
        return [
            GateResult(
                name="word_count",
                passed=False,
                score=2183.0,
                detail="实际 2183 字，目标 3000 字，容差 ±20% (2400-3600)",
                payload={
                    "actual": 2183,
                    "target": 3000,
                    "min_words": 2400,
                    "max_words": 3600,
                },
            )
        ]

    def test_feedback_states_shortfall_in_words(self):
        from novel.auto import _build_retry_feedback

        fb = _build_retry_feedback(self._failed_word_gate(), {})
        # 2183 → 下限 2400，缺口约 217 字
        assert "2183" in fb
        assert "补足" in fb

    def test_feedback_forbids_repeating_existing_scenes(self):
        from novel.auto import _build_retry_feedback

        fb = _build_retry_feedback(self._failed_word_gate(), {})
        assert "重复" in fb

    def test_feedback_still_lists_other_failed_gates(self):
        from novel.auto import _build_retry_feedback

        gates = self._failed_word_gate() + [
            GateResult(name="ai_flavor", passed=False, score=61.0, detail="AI 味指数 61（阈值 < 50）"),
        ]
        fb = _build_retry_feedback(gates, {})
        assert "ai_flavor" in fb
        assert "AI 味指数 61" in fb

    def test_standard_preset_runs_three_iters(self):
        """多跑一轮才有加长机会。"""
        from novel.auto_state import QualityPreset

        assert QualityPreset.STANDARD.iters == 3


# ---------------------------------------------------------------------------
# C. 并发 worker 不应再因 .content 崩溃
# ---------------------------------------------------------------------------

class TestParallelNoContentCrash:
    """ChapterResult 是元数据类，没有 content——并发路径曾每章抛 AttributeError。"""

    def test_parallel_phase_emits_no_attribute_error(self, tmp_path, monkeypatch, capsys):
        from novel.auto import run_auto_novel
        from novel.auto_state import AutoSpec, QualityPreset

        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")

        spec = AutoSpec(
            title="crash_regression",
            target_words=6000,
            target_chapters=4,
            quality=QualityPreset.DRAFT,
            parallel=3,
        )
        run_auto_novel(spec, tmp_path)

        out = capsys.readouterr().out
        assert "has no attribute 'content'" not in out
        assert "并发 worker 异常" not in out

    def test_parallel_phase_still_completes_chapters(self, tmp_path, monkeypatch):
        from novel.auto import run_auto_novel
        from novel.auto_state import AutoSpec, QualityPreset

        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")

        spec = AutoSpec(
            title="crash_regression2",
            target_words=6000,
            target_chapters=4,
            quality=QualityPreset.DRAFT,
            parallel=3,
        )
        run_auto_novel(spec, tmp_path)

        from novel.auto_state import AutoState
        state = AutoState.load(tmp_path)
        assert state is not None
        assert len(state.chapters_done) == 4


# ---------------------------------------------------------------------------
# F. 续跑时 state.phase 已是 done → out 未绑定崩溃
# ---------------------------------------------------------------------------

class TestResumeFromDonePhase:
    """daemon 结束会把 phase 标成 done；续跑时导出块被跳过，out 从未赋值。"""

    def test_resume_when_phase_is_done_does_not_crash(self, tmp_path, monkeypatch):
        from novel.auto import run_auto_novel
        from novel.auto_state import AutoSpec, AutoState, Phase, QualityPreset

        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")

        spec = AutoSpec(
            title="resume_done",
            target_words=6000,
            target_chapters=3,
            quality=QualityPreset.DRAFT,
            parallel=2,
        )
        run_auto_novel(spec, tmp_path)

        # 复现 daemon 中断后的状态：phase=done，但章节没写完
        state = AutoState.load(tmp_path)
        assert state is not None
        state.phase = Phase.DONE
        state.chapters_done = [1]
        state.save(tmp_path)

        # 续跑必须返回一个路径，而不是抛 UnboundLocalError
        out = run_auto_novel(spec, tmp_path, state=state)
        assert out is not None


# ---------------------------------------------------------------------------
# 回归护栏：auto_control.json 的形状别被改坏
# ---------------------------------------------------------------------------

class TestControlSignalRoundTrip:
    def test_signal_json_shape(self, tmp_path):
        ControlSignal.write(tmp_path, ControlSignal.STOP)
        raw = json.loads((tmp_path / ".novel" / "auto_control.json").read_text(encoding="utf-8"))
        assert raw["signal"] == "stop"
