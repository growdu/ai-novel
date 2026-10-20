"""v0.17 分块评估单测。

背景：长篇项目（400+ 章）不能把整书塞进一个 prompt——禹州项目实测
421 章拼接后 78 万字，单 prompt 必炸。改成按批切 + 逐批评 + 聚合。

覆盖：
  1. plan_batches / plan_batches_by_chars —— 切块与重叠窗口
  2. 章号解析与防幻觉 —— LLM 编造不存在的章号必须被丢弃
  3. _aggregate_batch_reports —— 聚合语义（全批通过才算过、并集、去重）
  4. evaluate_batches 端到端 —— 多批 / 失败批 / 全批失败的 fail-safe
  5. build_daemon_criteria_batch_messages —— 字数表注入
"""
from __future__ import annotations

import json

from novel.criteria import (
    CriterionResult,
    EvaluatorReport,
    _aggregate_batch_reports,
    _coerce_int_list,
    _parse_report,
    evaluate_batches,
    plan_batches,
    plan_batches_by_chars,
)
from novel.prompts import build_daemon_criteria_batch_messages


# ---------------------------------------------------------------------------
# 1. 切块
# ---------------------------------------------------------------------------

class TestPlanBatches:
    def test_empty(self):
        assert plan_batches(0) == []
        assert plan_batches(-3) == []

    def test_single_batch_when_fits(self):
        assert plan_batches(5, batch_size=12, overlap=4) == [(0, 5)]

    def test_overlap_windows(self):
        assert plan_batches(10, batch_size=4, overlap=1) == [(0, 4), (3, 7), (6, 10)]

    def test_no_overlap(self):
        assert plan_batches(6, batch_size=3, overlap=0) == [(0, 3), (3, 6)]

    def test_overlap_clamped_below_batch_size(self):
        """overlap >= batch_size 会被夹到 batch_size-1（step=1），避免死循环。"""
        got = plan_batches(10, batch_size=3, overlap=9)
        assert got == [(0, 3), (1, 4), (2, 5), (3, 6),
                       (4, 7), (5, 8), (6, 9), (7, 10)]

    def test_covers_everything(self):
        """不管参数怎么切，最后一章必须被覆盖到。"""
        for n in (1, 7, 23, 421):
            for bs in (1, 5, 12, 50):
                for ov in (0, 3, 11):
                    ranges = plan_batches(n, bs, ov)
                    assert ranges[-1][1] == n, (n, bs, ov, ranges)
                    assert ranges[0][0] == 0


class TestPlanBatchesByChars:
    def test_respects_max_chars(self):
        """每章 1000 字、上限 3000 字 → 每批最多 3 章。"""
        chs = [{"no": i, "text": "字" * 1000} for i in range(1, 10)]
        got = plan_batches_by_chars(chs, batch_size=12, overlap=0, max_chars=3000)
        assert all((e - s) <= 3 for s, e in got)

    def test_respects_batch_size(self):
        chs = [{"no": i, "text": "字" * 10} for i in range(1, 10)]
        got = plan_batches_by_chars(chs, batch_size=3, overlap=0, max_chars=10_000)
        assert all((e - s) <= 3 for s, e in got)

    def test_long_chapter_alone(self):
        """单章就超上限时不能死循环——至少收一章。"""
        chs = [{"no": i, "text": "字" * 9999} for i in range(1, 4)]
        got = plan_batches_by_chars(chs, batch_size=12, overlap=0, max_chars=100)
        assert got == [(0, 1), (1, 2), (2, 3)]

    def test_covers_tail(self):
        chs = [{"no": i, "text": "字" * 500} for i in range(1, 8)]
        got = plan_batches_by_chars(chs, batch_size=12, overlap=2, max_chars=1200)
        assert got[-1][1] == 7

    def test_empty(self):
        assert plan_batches_by_chars([]) == []


# ---------------------------------------------------------------------------
# 2. 章号解析与防幻觉
# ---------------------------------------------------------------------------

class TestCoerceIntList:
    def test_sorted_dedup(self):
        assert _coerce_int_list([7, 3, 3, 1]) == [1, 3, 7]

    def test_drops_junk(self):
        assert _coerce_int_list([3, "x", None, "12", 2.0]) == [2, 3, 12]

    def test_scalar(self):
        assert _coerce_int_list(5) == [5]

    def test_bool_ignored(self):
        assert _coerce_int_list(True) == []

    def test_non_list_empty(self):
        assert _coerce_int_list(None) == []
        assert _coerce_int_list("abc") == []


class TestParseReportFailedChapters:
    def test_criterion_level_chapters(self):
        parsed = {
            "summary": "s", "all_passed": False,
            "criteria": [
                {"id": 1, "text": "a", "passed": False, "failed_chapters": [2, 9]},
            ],
            "failed_chapters": [2, 9],
        }
        rep = _parse_report(parsed)
        assert rep.failed_chapters == [2, 9]
        assert rep.criteria[0].failed_chapters == [2, 9]

    def test_missing_field_defaults_empty(self):
        rep = _parse_report({"summary": "s", "all_passed": True,
                             "criteria": [{"id": 1, "text": "a", "passed": True}]})
        assert rep.failed_chapters == []
        assert rep.criteria[0].failed_chapters == []


# ---------------------------------------------------------------------------
# 3. 聚合
# ---------------------------------------------------------------------------

class TestAggregateBatchReports:
    def test_all_batches_must_pass(self):
        """一条指标只要有任一批没过，整体就是没过。"""
        ok = EvaluatorReport(summary="", all_passed=True,
                              criteria=[CriterionResult(1, "c1", True)])
        bad = EvaluatorReport(summary="", all_passed=False,
                              criteria=[CriterionResult(1, "c1", False,
                                                        evidence="e", suggestion="s",
                                                        failed_chapters=[5])])
        agg = _aggregate_batch_reports([ok, bad], [(0, 3), (3, 6)], ["c1"])
        assert agg.all_passed is False
        assert agg.criteria[0].failed_chapters == [5]
        assert agg.criteria[0].evidence == "e"

    def test_failed_chapters_union_sorted(self):
        a = EvaluatorReport(summary="", all_passed=False, failed_chapters=[9, 3])
        b = EvaluatorReport(summary="", all_passed=False, failed_chapters=[3, 5])
        agg = _aggregate_batch_reports([a, b], [(0, 3), (3, 6)], ["c"])
        assert agg.failed_chapters == [3, 5, 9]

    def test_missing_criterion_treated_as_pass(self):
        """模型在某批漏报某条指标时不能反过来判它失败。"""
        one = EvaluatorReport(summary="", all_passed=True, criteria=[
            CriterionResult(1, "c1", True), CriterionResult(2, "c2", True)])
        two = EvaluatorReport(summary="", all_passed=True, criteria=[CriterionResult(1, "c1", True)])
        agg = _aggregate_batch_reports([one, two], [(0, 2), (2, 4)], ["c1", "c2"])
        assert agg.all_passed is True
        assert len(agg.criteria) == 2

    def test_all_passed_when_clean(self):
        r = EvaluatorReport(summary="", all_passed=True, criteria=[CriterionResult(1, "c1", True)])
        agg = _aggregate_batch_reports([r, r], [(0, 2), (2, 4)], ["c1"])
        assert agg.all_passed is True
        assert agg.failed_chapters == []

    def test_fixes_deduped_and_capped(self):
        rs = [EvaluatorReport(summary="", all_passed=False, top_priority_fixes=[f"fix{i}", "common"])
              for i in range(6)]
        agg = _aggregate_batch_reports(rs, [(0, 1)] * 6, ["c"])
        assert "common" in agg.top_priority_fixes
        assert len(agg.top_priority_fixes) == len(set(agg.top_priority_fixes))
        assert len(agg.top_priority_fixes) <= 8

    def test_failed_sorted_first(self):
        r = EvaluatorReport(summary="", all_passed=False, criteria=[
            CriterionResult(1, "a", True), CriterionResult(2, "b", False)])
        agg = _aggregate_batch_reports([r], [(0, 3)], ["a", "b"])
        assert [c.id for c in agg.criteria] == [2, 1]


# ---------------------------------------------------------------------------
# 4. evaluate_batches 端到端
# ---------------------------------------------------------------------------

class _FakeClient:
    """按调用次序依次返回预设内容；记录每次的 prompt。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts = []
        self.calls = 0

    def chat(self, *a, **k):
        raise AssertionError("evaluate_batches 不该走 chat()")

    def chat_with_continuation(self, msgs, *a, **k):
        self.prompts.append(msgs)
        self.calls += 1
        idx = min(self.calls - 1, len(self._responses) - 1)

        class _R:
            content = self._responses[idx]
            raw = {"choices": [{"finish_reason": "stop"}]}
            total_tokens = 100

        return _R()


def _json_response(payload: dict) -> str:
    return "分析如下：\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def _chapters(n: int, start: int = 1) -> list[dict]:
    return [{"no": start + i, "title": f"T{start + i}", "words": 1000,
             "text": "正文" * 500} for i in range(n)]


class TestEvaluateBatches:
    def test_no_criteria_passes(self):
        rep = evaluate_batches([], _chapters(5), client=_FakeClient(["{}"]))
        assert rep.all_passed is True

    def test_no_chapters_fails(self):
        rep = evaluate_batches(["c1"], [], client=_FakeClient(["{}"]))
        assert rep.all_passed is False

    def test_single_batch(self):
        c = _FakeClient([_json_response({
            "summary": "ok", "all_passed": True, "failed_chapters": [],
            "criteria": [{"id": 1, "text": "c1", "passed": True}],
        })])
        rep = evaluate_batches(["c1"], _chapters(4), batch_size=12, client=c)
        assert rep.all_passed is True
        assert c.calls == 1

    def test_multi_batch_union_and_and_semantics(self):
        """两批：第 1 批过、第 2 批挂 → 整体不过，failed_chapters 取并集。"""
        c = _FakeClient([
            _json_response({"summary": "a", "all_passed": True, "failed_chapters": [],
                            "criteria": [{"id": 1, "text": "c1", "passed": True}]}),
            _json_response({"summary": "b", "all_passed": False,
                            "failed_chapters": [6],
                            "criteria": [{"id": 1, "text": "c1", "passed": False,
                                          "failed_chapters": [6], "evidence": "太短"}]}),
        ])
        rep = evaluate_batches(["c1"], _chapters(8), batch_size=4, overlap=0, client=c)
        assert c.calls == 2
        assert rep.all_passed is False
        assert rep.failed_chapters == [6]
        assert rep.criteria[0].evidence == "太短"

    def test_fabricated_chapter_numbers_dropped(self):
        """LLM 编一个本批不存在的章号 → 丢弃，否则 surgical 会去重写不存在的章。"""
        c = _FakeClient([_json_response({
            "summary": "x", "all_passed": False,
            "failed_chapters": [2, 9999],
            "criteria": [{"id": 1, "text": "c1", "passed": False,
                          "failed_chapters": [2, 9999]}],
        })])
        rep = evaluate_batches(["c1"], _chapters(4), batch_size=12, client=c)
        assert rep.failed_chapters == [2]
        assert rep.criteria[0].failed_chapters == [2]

    def test_failed_without_chapters_marks_whole_batch(self):
        """说没过却指不出具体章 → 保守把整批记为待重写，避免漏。"""
        c = _FakeClient([_json_response({
            "summary": "x", "all_passed": False, "failed_chapters": [],
            "criteria": [{"id": 1, "text": "c1", "passed": False,
                          "failed_chapters": []}],
        })])
        rep = evaluate_batches(["c1"], _chapters(3), batch_size=12, client=c)
        assert rep.failed_chapters == [1, 2, 3]

    def test_all_batches_fail_to_parse_is_failsafe(self):
        """全批垃圾输出时绝不能报「全通过」——否则 daemon 会误判达标退出。"""
        c = _FakeClient(["这不是 JSON", "也不是"])
        rep = evaluate_batches(["c1"], _chapters(6), batch_size=3, overlap=0, client=c)
        assert rep.all_passed is False
        assert "未产出可解析 JSON" in rep.summary

    def test_one_batch_raises_skipped_not_fatal(self):
        """单批抛异常只跳过该批，其余批照常聚合。"""
        class _Flaky(_FakeClient):
            def chat_with_continuation(self, msgs, *a, **k):
                if not self.calls:
                    self.calls += 1
                    raise RuntimeError("429 rate limited")
                return super().chat_with_continuation(msgs, *a, **k)

        good = _json_response({"summary": "ok", "all_passed": True, "failed_chapters": [],
                               "criteria": [{"id": 1, "text": "c1", "passed": True}]})
        c = _Flaky([good])
        rep = evaluate_batches(["c1"], _chapters(8), batch_size=4, overlap=0, client=c)
        assert rep.all_passed is True  # 第二批过了；第一批异常被跳过

    def test_on_progress_called_per_batch(self):
        seen = []
        c = _FakeClient([_json_response({"summary": "ok", "all_passed": True,
                                         "failed_chapters": [],
                                         "criteria": [{"id": 1, "text": "c1", "passed": True}]})])
        evaluate_batches(["c1"], _chapters(9), batch_size=3, overlap=0, client=c,
                         on_progress=lambda bi, tot, rep: seen.append((bi, tot)))
        assert [t for _, t in seen] == [3, 3, 3]
        assert [b for b, _ in seen] == [0, 1, 2]

    def test_raw_text_kept_for_debug(self):
        c = _FakeClient([_json_response({"summary": "ok", "all_passed": True,
                                         "failed_chapters": [],
                                         "criteria": [{"id": 1, "text": "c1", "passed": True}]})])
        rep = evaluate_batches(["c1"], _chapters(2), client=c)
        assert "batch 1/1" in rep.raw_text

    def test_overlap_reduces_boundary_blind_spot(self):
        """重叠模式下批次数比不重叠多，但覆盖章号并集仍是全书。"""
        c = _FakeClient([_json_response({"summary": "ok", "all_passed": True,
                                         "failed_chapters": [],
                                         "criteria": [{"id": 1, "text": "c1", "passed": True}]})])
        rep = evaluate_batches(["c1"], _chapters(10), batch_size=4, overlap=1, client=c)
        assert rep.all_passed is True
        assert c.calls == 3  # (0,4) (3,7) (6,10)


# ---------------------------------------------------------------------------
# 5. prompt 构建
# ---------------------------------------------------------------------------

class TestBatchMessages:
    def test_word_count_table_present(self):
        msgs = build_daemon_criteria_batch_messages(
            ["每章不少于3000字"], [{"no": 7, "title": "逃亡", "words": 3120, "text": "正文"}],
        )
        user = msgs[1].content
        assert "第7章 逃亡：3120 字" in user
        assert "正文" in user

    def test_batch_note_injected(self):
        msgs = build_daemon_criteria_batch_messages(
            ["c"], [{"no": 1, "title": "t", "words": 10, "text": "x"}],
            batch_note="本批第 1–1 章",
        )
        assert "本批第 1–1 章" in msgs[1].content

    def test_prev_feedback_injected(self):
        msgs = build_daemon_criteria_batch_messages(
            ["c"], [{"no": 1, "title": "t", "words": 10, "text": "x"}],
            prev_feedback="上轮第3章太短",
        )
        assert "上轮第3章太短" in msgs[1].content

    def test_uses_batch_prompt_not_full_book(self):
        """必须走分块模板，不是整书模板。"""
        msgs = build_daemon_criteria_batch_messages(
            ["c"], [{"no": 1, "title": "t", "words": 10, "text": "x"}],
        )
        assert "failed_chapters" in msgs[0].content
        assert "本批" in msgs[0].content