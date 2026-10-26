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
from pathlib import Path

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
# G. token 快照必须读得懂 TokenTracker（auto 里 client 真正的类型）
# ---------------------------------------------------------------------------

class TestTokenSnapshotFromTracker:
    """run_auto_novel 把 client 包成 TokenTracker 再传下去——快照必须认它。"""

    def _tracker(self):
        from novel.token_tracker import TokenTracker

        return TokenTracker(client=object(), model="minimax-Text-01")

    def test_snapshot_reads_tracker_counters(self):
        from novel.auto import _client_token_snapshot

        tt = self._tracker()
        tt.record(1200, 800)
        assert _client_token_snapshot(tt) == (1200, 800, 2000)

    def test_snapshot_of_fresh_tracker_is_zero(self):
        from novel.auto import _client_token_snapshot

        assert _client_token_snapshot(self._tracker()) == (0, 0, 0)


class TestSyncCostFromClient:
    """评估等非写作路径的 token 也必须计入 state，否则预算护栏形同虚设。"""

    def test_sync_adds_delta_into_state(self):
        from novel.auto import _sync_cost_from_client
        from novel.auto_state import AutoState
        from novel.token_tracker import TokenTracker

        state = AutoState()
        tt = TokenTracker(client=object(), model="minimax-Text-01")
        tt.record(1000, 500)

        _sync_cost_from_client(state, (0, 0, 0), tt)

        assert state.cumulative_tokens == 1500
        assert state.cumulative_prompt_tokens == 1000
        assert state.cumulative_completion_tokens == 500
        assert state.cumulative_cost_cny > 0

    def test_sync_with_advanced_baseline_adds_only_increment(self):
        """baseline 前进后只计增量，不重复累加已入账的部分。"""
        from novel.auto import _sync_cost_from_client
        from novel.auto_state import AutoState
        from novel.token_tracker import TokenTracker

        state = AutoState()
        tt = TokenTracker(client=object(), model="minimax-Text-01")
        tt.record(1000, 500)
        _sync_cost_from_client(state, (0, 0, 0), tt)
        mid = state.cumulative_tokens

        tt.record(200, 100)
        _sync_cost_from_client(state, (1000, 500, 1500), tt)
        assert state.cumulative_tokens == mid + 300


class TestFlushCostIsIdempotent:
    """_flush_cost 收尾再调一次不能把成本翻倍——worker 已逐章入账。"""

    def _state_and_tracker(self):
        from novel.auto_state import AutoState
        from novel.token_tracker import TokenTracker

        return AutoState(), TokenTracker(client=object(), model="minimax-Text-01")

    def test_repeated_flush_does_not_double_count(self):
        from novel.auto import _flush_cost

        state, tt = self._state_and_tracker()
        tt.record(1000, 500)

        _flush_cost(state, tt)
        after_first = state.cumulative_tokens
        _flush_cost(state, tt)
        assert state.cumulative_tokens == after_first

    def test_flush_picks_up_new_usage(self):
        from novel.auto import _flush_cost

        state, tt = self._state_and_tracker()
        tt.record(1000, 500)
        _flush_cost(state, tt)
        mid = state.cumulative_tokens

        tt.record(400, 200)
        _flush_cost(state, tt)
        assert state.cumulative_tokens == mid + 600


# ---------------------------------------------------------------------------
# H. surgical 重建不能被 state.phase 挡住
# ---------------------------------------------------------------------------

class TestSurgicalRebuildNotBlocked:
    """phase=done 时续跑，surgical 的 only_chapters 仍必须真的走写作阶段。"""

    def test_writing_phase_runs_for_surgical_despite_done_phase(self, tmp_path, monkeypatch):
        import novel.auto as auto_mod
        from novel.auto import run_auto_novel
        from novel.auto_state import AutoSpec, AutoState, Phase, QualityPreset

        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")

        calls: list = []
        real = auto_mod._writing_phase

        def spy(spec, project, client, state, only_chapters=None):
            calls.append(only_chapters)
            return real(spec, project, client, state, only_chapters=only_chapters)

        monkeypatch.setattr(auto_mod, "_writing_phase", spy)

        spec = AutoSpec(
            title="surgical_phase",
            target_words=9000,
            target_chapters=5,
            quality=QualityPreset.DRAFT,
            parallel=2,
        )
        run_auto_novel(spec, tmp_path)

        state = AutoState.load(tmp_path)
        assert state is not None
        state.phase = Phase.DONE
        state.save(tmp_path)

        calls.clear()
        run_auto_novel(spec, tmp_path, state=state, only_chapters=[3])

        assert calls == [{3}]


# ---------------------------------------------------------------------------
# I. daemon 首轮也必须拿到重写目标（否则续跑等于只评估）
# ---------------------------------------------------------------------------

class TestRewriteTargets:
    """daemon 每轮的第 1 次迭代 last_report=None——重写目标必须能从 state 取。"""

    def _state(self):
        from novel.auto_state import AutoState

        state = AutoState(chapters_total=10)
        state.last_failed_chapters = [1, 2, 3]
        state.passed_chapters = [4, 5, 6, 7, 8, 9, 10]
        state.last_iter_passed = False
        return state

    def test_uses_persisted_failures_when_no_report(self):
        from novel.daemon import _rewrite_targets

        assert _rewrite_targets(self._state(), None, 10) == [1, 2, 3]

    def test_none_when_previous_iteration_passed(self):
        from novel.daemon import _rewrite_targets

        state = self._state()
        state.last_iter_passed = True
        assert _rewrite_targets(state, None, 10) is None

    def test_none_when_no_failures_recorded(self):
        from novel.daemon import _rewrite_targets

        state = self._state()
        state.last_failed_chapters = []
        assert _rewrite_targets(state, None, 10) is None

    def test_excludes_chapters_already_passed(self):
        from novel.daemon import _rewrite_targets

        state = self._state()
        state.last_failed_chapters = [1, 2, 3, 5]
        state.passed_chapters = [4, 5, 6, 7, 8, 9, 10]
        assert _rewrite_targets(state, None, 10) == [1, 2, 3]

    def test_report_takes_precedence_over_state(self):
        from novel.daemon import _rewrite_targets

        class _R:
            all_passed = False
            failed_chapters = [7, 8]

        state = self._state()
        state.passed_chapters = [1, 2, 3, 4, 5, 6, 9, 10]
        assert _rewrite_targets(state, _R(), 10) == [7, 8]


# ---------------------------------------------------------------------------
# J. 字数标准必须落在模型真实产能内
# ---------------------------------------------------------------------------

# 实测 daemon 跑出来的章节长度（v0.19 验证跑：41/42 章 + 历史 37 章）
OBSERVED_CHAPTER_LENGTHS = (1704, 1780, 1811, 1864, 1900, 2037, 2065, 2196, 2333)


class TestWordCountStandardIsAchievable:
    """门槛定在模型做不到的位置 = daemon 无限重写同一批章节，烧钱不产出。"""

    def test_project_per_chapter_words_is_2000(self):
        from novel.commands._daemon import _load_or_init_spec

        proj = Path(__file__).resolve().parents[1] / "text/yuzhou_chuanshuo/第一部_第三秩序"
        spec = _load_or_init_spec(proj, "第七界域")

        assert spec.per_chapter_words == 2000, (
            f"per_chapter_words={spec.per_chapter_words}，"
            f"全书 {spec.target_words} 字 / {spec.target_chapters} 章"
        )

    def test_every_observed_chapter_length_passes_the_gate(self):
        """实测产出过的长度必须全部过门控，否则这些章会被反复重写。"""
        from novel.auto_state import AutoSpec, QualityPreset
        from novel.quality_gates import check_word_count

        spec = AutoSpec(
            title="t",
            target_words=2000 * 421,
            target_chapters=421,
            quality=QualityPreset.STANDARD,
        )
        assert spec.per_chapter_words == 2000

        failed = [
            n
            for n in OBSERVED_CHAPTER_LENGTHS
            if not check_word_count(
                "字" * n, spec.per_chapter_words, spec.quality.word_tolerance
            ).passed
        ]
        assert failed == [], f"这些实测长度过不了门控：{failed}"

    def test_criteria_md_word_range_matches_the_gate(self):
        """criteria.md 与硬门控口径必须一致，否则 LLM 评估会重复报同一个问题。"""
        proj = Path(__file__).resolve().parents[1] / "text/yuzhou_chuanshuo/第一部_第三秩序"
        text = (proj / ".novel" / "criteria.md").read_text(encoding="utf-8")
        assert "3000 字" not in text, "criteria.md 仍写着 3000 字门槛"


# ---------------------------------------------------------------------------
# K. 阶段级停止：润色/一致性/导出也必须能停
# ---------------------------------------------------------------------------

class TestPhaseLevelStop:
    """停止信号与预算都只在写作阶段检查——润色阶段曾完全无法中断。"""

    def _project(self, tmp_path):
        from novel.storage import Project, init_project

        if not (tmp_path / ".novel").exists():
            init_project(tmp_path, "stop_test")
        return Project(
            root=tmp_path.resolve(),
            title="stop_test",
            meta={"genre": "科幻末世"},
        )

    def _state(self, tmp_path):
        from novel.auto_state import AutoSpec, AutoState

        spec = AutoSpec(title="stop_test", target_words=6000, target_chapters=3)
        state = AutoState(spec=spec.__dict__, chapters_total=3)
        state.chapters_failed = [1, 2, 3]
        state.save(tmp_path)
        return state

    def _spec(self):
        from novel.auto_state import AutoSpec, QualityPreset

        return AutoSpec(
            title="stop_test",
            target_words=6000,
            target_chapters=3,
            quality=QualityPreset.STANDARD,
        )

    def test_polishing_stops_on_stop_signal(self, tmp_path, monkeypatch):
        from novel.auto import _polishing_phase, _StopRun

        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")
        project = self._project(tmp_path)
        (tmp_path / ".novel" / "stop_daemon").write_text("", encoding="utf-8")

        with pytest.raises(_StopRun):
            _polishing_phase(self._spec(), project, object(), self._state(tmp_path))

    def test_polishing_stops_when_budget_exhausted(self, tmp_path, monkeypatch):
        from novel.auto import _polishing_phase, _StopRun

        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")

        state = self._state(tmp_path)
        state.budget_cny = 0.10
        state.cumulative_cost_cny = 0.20

        with pytest.raises(_StopRun):
            _polishing_phase(self._spec(), self._project(tmp_path), object(), state)

    def test_polishing_continues_when_budget_ok(self, tmp_path, monkeypatch):
        """预算充足 + 无停止信号时不应误停。"""
        from novel.auto import _polishing_phase, _StopRun

        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")

        state = self._state(tmp_path)
        state.budget_cny = 10.0
        state.cumulative_cost_cny = 0.20

        try:
            _polishing_phase(self._spec(), self._project(tmp_path), object(), state)
        except _StopRun:
            pytest.fail("预算充足时不应触发停止")

    def test_budget_is_persisted_into_state(self, tmp_path, monkeypatch):
        """run_auto_novel 收到 budget_cny 必须写进 state，否则运行内无法判超支。"""
        from novel.auto import run_auto_novel
        from novel.auto_state import AutoSpec, AutoState, QualityPreset

        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")

        spec = AutoSpec(
            title="budget_state",
            target_words=6000,
            target_chapters=3,
            quality=QualityPreset.DRAFT,
        )
        run_auto_novel(spec, tmp_path, budget_cny=2.5)

        state = AutoState.load(tmp_path)
        assert state is not None
        assert state.budget_cny == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# L. 停止信号必须被完整消费（否则下次启动即自杀）
# ---------------------------------------------------------------------------

class TestStopSignalFullyConsumed:
    """daemon stop 写两套信号；消费时必须两套都清，否则重启直接自杀。"""

    def test_both_signals_cleared_when_stop_consumed(self, tmp_path):
        from novel.commands._daemon import _write_stop_file
        from novel.daemon import _stop_signal_path, is_stop_requested

        _write_stop_file(tmp_path)
        assert is_stop_requested(tmp_path) is True

        assert not _stop_signal_path(tmp_path).exists()
        assert ControlSignal.read(tmp_path) == ControlSignal.RUN

    def test_chapter_loop_does_not_see_stop_after_consumption(self, tmp_path):
        """消费完信号后，章级检查必须认为「没在停止」。"""
        from novel.auto import _stop_requested
        from novel.commands._daemon import _write_stop_file
        from novel.daemon import is_stop_requested

        _write_stop_file(tmp_path)
        is_stop_requested(tmp_path)

        assert _stop_requested(tmp_path) is False

    def test_stop_signal_survives_when_no_stop_requested(self, tmp_path):
        """没写信号时不应凭空造出 auto_control.json。"""
        from novel.daemon import is_stop_requested

        (tmp_path / ".novel").mkdir()
        assert is_stop_requested(tmp_path) is False
        assert ControlSignal.read(tmp_path) == ControlSignal.RUN


# ---------------------------------------------------------------------------
# M. 停止信号下并发写作不应刷 worker 异常
# ---------------------------------------------------------------------------

class TestParallelStopsQuietly:
    def test_no_worker_exception_spam_when_stopped(self, tmp_path, monkeypatch, capsys):
        from novel.auto import run_auto_novel
        from novel.auto_state import AutoSpec, QualityPreset

        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")

        from novel.storage import init_project

        init_project(tmp_path, "quiet_stop")
        ControlSignal.write(tmp_path, ControlSignal.STOP)

        spec = AutoSpec(
            title="quiet_stop",
            target_words=9000,
            target_chapters=6,
            quality=QualityPreset.DRAFT,
            parallel=3,
        )
        run_auto_novel(spec, tmp_path)

        out = capsys.readouterr().out
        assert "并发 worker 异常" not in out


# ---------------------------------------------------------------------------
# N. DOWNGRADE 信号必须真的降级
# ---------------------------------------------------------------------------

class TestDowngradeSignalWorks:
    """_DOWNGRADE_REQUESTED 此前只写不读——web UI 的降级按钮完全无效。"""

    def _spec(self):
        from novel.auto_state import AutoSpec, QualityPreset

        return AutoSpec(
            title="dg",
            target_words=6000,
            target_chapters=3,
            quality=QualityPreset.STANDARD,
        )

    def test_downgrade_signal_switches_quality_to_draft(self, tmp_path):
        from novel.auto import _apply_downgrade, _check_control_signal

        (tmp_path / ".novel").mkdir()
        ControlSignal.write(tmp_path, ControlSignal.DOWNGRADE)
        _check_control_signal(tmp_path)

        spec = self._spec()
        _apply_downgrade(spec, tmp_path)
        assert spec.quality.value == "draft"

    def test_no_signal_leaves_quality_untouched(self, tmp_path):
        from novel.auto import _apply_downgrade, _check_control_signal

        (tmp_path / ".novel").mkdir()
        ControlSignal.write(tmp_path, ControlSignal.RUN)
        _check_control_signal(tmp_path)

        spec = self._spec()
        _apply_downgrade(spec, tmp_path)
        assert spec.quality.value == "standard"


# ---------------------------------------------------------------------------
# O. AI 味门控改用「具体问题条数」判据
# ---------------------------------------------------------------------------

def _detect_report(score: int, issues: int) -> str:
    """构造一份与真实 detect 报告同构的文本。"""
    lines = [f"### AI 味指数：{score}/100", "", "### 具体问题与建议：", ""]
    for i in range(1, issues + 1):
        lines.append(f'#### {i}. [第{i}段] "原文{i}" → 问题：套话堆砌，建议改为：动作化描写。')
    return "\n".join(lines)


class TestAiFlavorGateUsesIssueCount:
    """实测：自评指数与实际列出的问题数几乎不相关（r=0.177），判据要换。"""

    def _proj(self, tmp_path):
        from novel import storage as S

        target = tmp_path / "p"
        target.mkdir()
        proj = S.init_project(target, "T", meta={"genre": "科幻末世"})
        S.save_chapter(proj, 1, "正文" * 50)
        return proj

    def test_issue_count_parsed_from_report(self):
        from novel.quality_gates import count_ai_issues

        text = _detect_report(75, 3)
        assert count_ai_issues(text) == 3

    def test_issue_count_zero_for_plain_text(self):
        from novel.quality_gates import count_ai_issues

        assert count_ai_issues("AI 味指数：65") == 0

    def test_few_issues_passes_even_with_high_score(self, tmp_path):
        """问题少就是好——指数再高也不该卡。"""
        from novel import quality_gates as QG
        from novel.llm import LLMResult

        class _C:
            def chat(self, *a, **k):
                return LLMResult(content=_detect_report(85, 4), model="fake")

        r = QG.check_ai_flavor(self._proj(tmp_path), 1, client=_C(), threshold=70)
        assert r.passed is True
        assert "4" in r.detail

    def test_many_issues_and_high_score_fails(self, tmp_path):
        from novel import quality_gates as QG
        from novel.llm import LLMResult

        class _C:
            def chat(self, *a, **k):
                return LLMResult(content=_detect_report(85, 12), model="fake")

        r = QG.check_ai_flavor(self._proj(tmp_path), 1, client=_C(), threshold=70)
        assert r.passed is False
        assert "12" in r.detail

    def test_many_issues_but_low_score_passes(self, tmp_path):
        """问题多但指数低于阈值时按通过处理（两条路任一满足即可）。"""
        from novel import quality_gates as QG
        from novel.llm import LLMResult

        class _C:
            def chat(self, *a, **k):
                return LLMResult(content=_detect_report(65, 12), model="fake")

        r = QG.check_ai_flavor(self._proj(tmp_path), 1, client=_C(), threshold=70)
        assert r.passed is True

    def test_standard_threshold_relaxed_to_70(self):
        from novel.auto_state import QualityPreset

        assert QualityPreset.STANDARD.ai_flavor_threshold == 70


# ---------------------------------------------------------------------------
# P. 环境变量必须优先于 .env（干跑开关不能被静默覆盖）
# ---------------------------------------------------------------------------

class TestEnvOverridesDotenv:
    """load_global 过去用 os.environ[k]=v 覆盖外部环境变量。"""

    def test_env_var_wins_over_dotenv(self, tmp_path, monkeypatch):
        """DRY_RUN=true 传进环境，.env 里写 false 时仍须为 true。"""
        from novel.config import load_global

        (tmp_path / ".env").write_text(
            "DRY_RUN=false\nOPENAI_API_KEY=from-dotenv\n", encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DRY_RUN", "true")

        cfg = load_global()
        assert cfg.dry_run is True

    def test_dotenv_still_fills_missing_vars(self, tmp_path, monkeypatch):
        """没设过的变量仍从 .env 取。"""
        from novel.config import load_global

        (tmp_path / ".env").write_text(
            "DRY_RUN=false\nOPENAI_MODEL=dotenv-model\n", encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        monkeypatch.delenv("DRY_RUN", raising=False)

        cfg = load_global()
        assert cfg.model == "dotenv-model"
        assert cfg.dry_run is False


# ---------------------------------------------------------------------------
# Q. 分数解析必须容得下模型的各种排版
# ---------------------------------------------------------------------------

class TestScoreParsingRobustness:
    """模型有时把数值放到下一行并加粗——正则失配会让门控静默放行。"""

    def test_radar_score_with_colon_on_same_line(self):
        from novel.quality_gates import parse_radar_score

        assert parse_radar_score("### 1. 总相似度：82") == 82

    def test_radar_score_on_next_line_bold(self):
        from novel.quality_gates import parse_radar_score

        assert parse_radar_score("#### 1. 总相似度\n**75/100**") == 75

    def test_radar_score_with_slash_suffix(self):
        from novel.quality_gates import parse_radar_score

        assert parse_radar_score("总相似度：82/100") == 82

    def test_radar_score_bold_same_line(self):
        from novel.quality_gates import parse_radar_score

        assert parse_radar_score("**总相似度：82**") == 82

    def test_ai_score_on_next_line_bold(self):
        from novel.quality_gates import parse_ai_flavor_score

        assert parse_ai_flavor_score("### AI 味指数\n**65/100**") == 65

    def test_ai_score_bold_same_line(self):
        from novel.quality_gates import parse_ai_flavor_score

        assert parse_ai_flavor_score("**AI 味指数：45**") == 45

    def test_ai_score_with_slash_suffix(self):
        from novel.quality_gates import parse_ai_flavor_score

        assert parse_ai_flavor_score("AI 味指数：75/100") == 75

    def test_no_number_still_returns_none(self):
        from novel.quality_gates import parse_ai_flavor_score, parse_radar_score

        assert parse_radar_score("无法判断") is None
        assert parse_ai_flavor_score("") is None


# ---------------------------------------------------------------------------
# R. 生成失败绝不能用占位符覆盖已有正文
# ---------------------------------------------------------------------------

class TestFailureKeepsExistingContent:
    """实测 285 章被限流失败后写进占位符，原正文被覆盖掉。"""

    def _setup(self, tmp_path, monkeypatch):
        from novel import storage as S
        from novel.auto_state import AutoSpec, AutoState, QualityPreset

        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")

        proj = S.init_project(tmp_path, "keep", meta={"genre": "科幻末世"})
        S.save_chapter(proj, 1, "这是原本写好的正文，不该被占位符覆盖。" * 30)

        spec = AutoSpec(
            title="keep",
            target_words=6000,
            target_chapters=3,
            quality=QualityPreset.STANDARD,
        )
        state = AutoState(spec=spec.__dict__, chapters_total=3)
        return proj, spec, state

    def _boom_client(self):
        class _C:
            def chat(self, *a, **k):
                raise RuntimeError("rate limit: 429")

            def chat_with_continuation(self, *a, **k):
                raise RuntimeError("rate limit: 429")

        return _C()

    def test_existing_chapter_survives_generation_failure(self, tmp_path, monkeypatch):
        from novel import storage as S
        from novel.auto import _write_one_chapter_locked

        proj, spec, state = self._setup(tmp_path, monkeypatch)

        _write_one_chapter_locked(
            spec, proj, 1, self._boom_client(), state, lambda **k: None
        )

        content = S.load_chapter(proj, 1) or ""
        assert "自动生成失败占位" not in content
        assert "原本写好的正文" in content

    def test_result_reports_existing_word_count(self, tmp_path, monkeypatch):
        """失败时 word_count 应反映保留的正文，而不是 0。"""
        from novel.auto import _write_one_chapter_locked

        proj, spec, state = self._setup(tmp_path, monkeypatch)

        result = _write_one_chapter_locked(
            spec, proj, 1, self._boom_client(), state, lambda **k: None
        )
        assert result.status == "failed"
        assert result.word_count > 0


# ---------------------------------------------------------------------------
# 回归护栏：auto_control.json 的形状别被改坏
# ---------------------------------------------------------------------------

class TestControlSignalRoundTrip:
    def test_signal_json_shape(self, tmp_path):
        ControlSignal.write(tmp_path, ControlSignal.STOP)
        raw = json.loads((tmp_path / ".novel" / "auto_control.json").read_text(encoding="utf-8"))
        assert raw["signal"] == "stop"
