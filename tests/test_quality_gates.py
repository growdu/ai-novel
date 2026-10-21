"""novel.quality_gates 测试：字数、AI 味、雷达、解析正则。"""
from __future__ import annotations

import pytest

from novel.auto_state import QualityPreset
from novel.quality_gates import (
    GateResult,
    check_word_count,
    parse_ai_flavor_score,
    parse_radar_score,
)


class TestCheckWordCount:
    def test_within_tolerance_passes(self):
        # chapter_word_count: Chinese 1 char = 1 word, English "hello" = 1 word
        # "hello " = 1 word per repeat. Need 3000 words total.
        text = "你好世界" * 750  # 4 chars * 750 = 3000 字
        r = check_word_count(text, target=3000, tolerance=0.1)
        assert r.passed is True
        assert r.score > 0

    def test_too_few_words_fails(self):
        text = "你好" * 500  # 1000 字
        r = check_word_count(text, target=3000, tolerance=0.1)
        assert r.passed is False
        assert "过少" in r.detail or "实际" in r.detail

    def test_target_zero_passes(self):
        r = check_word_count("anything", target=0, tolerance=0.1)
        assert r.passed is True

    def test_just_above_threshold(self):
        text = "字" * 2701  # 2701 个中文字
        r = check_word_count(text, target=3000, tolerance=0.1)
        assert r.passed is True

    def test_just_below_threshold(self):
        text = "字" * 2699  # 2699 个中文字
        r = check_word_count(text, target=3000, tolerance=0.1)
        assert r.passed is False


class TestParseAIFlavor:
    def test_extracts_chinese(self):
        assert parse_ai_flavor_score("AI 味指数：42") == 42

    def test_extracts_no_space(self):
        assert parse_ai_flavor_score("AI味指数:50") == 50

    def test_extracts_with_space(self):
        assert parse_ai_flavor_score("AI 味指数: 25") == 25

    def test_none_when_missing(self):
        assert parse_ai_flavor_score("no number here") is None

    def test_empty_string(self):
        assert parse_ai_flavor_score("") is None


class TestParseRadar:
    def test_extracts_int(self):
        assert parse_radar_score("总相似度：78") == 78

    def test_extracts_with_space(self):
        assert parse_radar_score("总相似度: 90") == 90

    def test_none_when_missing(self):
        assert parse_radar_score("没有数字") is None


class TestGateResult:
    def test_bool(self):
        assert bool(GateResult(name="x", passed=True)) is True
        assert bool(GateResult(name="x", passed=False)) is False


class TestQualityPresetThresholds:
    """验证 quality preset 的阈值被串门/引用的关键参数与文档一致。"""

    def test_premium_radar_threshold(self):
        assert QualityPreset.PREMIUM.radar_threshold == 70

    def test_premium_ai_threshold(self):
        assert QualityPreset.PREMIUM.ai_flavor_threshold == 30

    def test_premium_word_tolerance(self):
        assert QualityPreset.PREMIUM.word_tolerance == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# v0.14.x 测试深度补齐：run_all_gates 聚合 + 检查 LLM 的 gate 行为
# ---------------------------------------------------------------------------

import re
from unittest.mock import MagicMock

from novel.quality_gates import (
    GateResult,
    check_ai_flavor,
    check_consistency,
    check_radar,
    check_word_count,
    parse_ai_flavor_score,
    parse_radar_score,
    run_all_gates,
    summarize,
)


def _fake_project(tmp_path, *, chapter_text="", samples_text=None):
    """构造一个最小可用的 Project + 写入第 1 章。"""
    from novel import storage as S
    from novel.auto_state import AutoSpec
    target = tmp_path / "novel_p"
    target.mkdir()
    proj = S.init_project(target, "T", meta={"genre": "现实", "target_words": 9000})
    if chapter_text:
        S.save_chapter(proj, 1, chapter_text)
    if samples_text is not None:
        proj.samples_dir.mkdir(parents=True, exist_ok=True)
        (proj.samples_dir / "demo.md").write_text(samples_text, encoding="utf-8")
    return proj


class _FakeLLM:
    """最小的 LLMClient mock：任何 .chat() 调用返固定 content。"""
    def __init__(self, content="AI 味指数：40"):
        from novel.llm import LLMResult
        self._result = LLMResult(content=content, model="fake", elapsed_ms=1)
    def chat(self, *args, **kwargs):
        return self._result
    def chat_with_continuation(self, *args, **kwargs):
        return self._result


class TestCheckAIFlavor:
    """check_ai_flavor 行为：threshold=数值 vs None（跳过）。"""

    def test_threshold_none_skips(self, tmp_path):
        proj = _fake_project(tmp_path, chapter_text="内容")
        r = check_ai_flavor(proj, 1, client=_FakeLLM(), threshold=None)
        assert r.passed is True
        assert "未启用" in r.detail

    def test_below_threshold_passes(self, tmp_path):
        """score < threshold → pass。"""
        from novel import quality_gates as QG
        client = _FakeLLM(content="AI 味指数：25")
        proj = _fake_project(tmp_path, chapter_text="内容")
        r = QG.check_ai_flavor(proj, 1, client=client, threshold=30)
        assert r.passed is True  # 25 < 30
        assert r.score == 25

    def test_above_threshold_fails(self, tmp_path):
        from novel import quality_gates as QG
        client = _FakeLLM(content="AI 味指数：50")
        proj = _fake_project(tmp_path, chapter_text="内容")
        r = QG.check_ai_flavor(proj, 1, client=client, threshold=30)
        assert r.passed is False  # 50 >= 30
        assert r.score == 50

    def test_unparseable_score_skips_as_pass(self, tmp_path):
        """LLM 返了奇怪文本 → parse 失败 → 默认 pass（不阻塞）。"""
        from novel import quality_gates as QG
        client = _FakeLLM(content="无法判断")
        proj = _fake_project(tmp_path, chapter_text="内容")
        r = QG.check_ai_flavor(proj, 1, client=client, threshold=30)
        assert r.passed is True
        assert "无法解析" in r.detail


class TestCheckRadar:
    """check_radar 行为：threshold + samples 检查。"""

    def test_threshold_none_skips(self, tmp_path):
        proj = _fake_project(tmp_path)
        r = check_radar(proj, 1, client=_FakeLLM(), threshold=None)
        assert r.passed is True
        assert "未启用" in r.detail

    def test_no_samples_skips(self, tmp_path):
        """没有 samples/ 时跳过（雷达要有作者参考样本）。"""
        proj = _fake_project(tmp_path, samples_text=None)
        r = check_radar(proj, 1, client=_FakeLLM(), threshold=70)
        assert r.passed is True
        assert "samples/ 为空" in r.detail

    def test_above_threshold_passes(self, tmp_path):
        """相似度 ≥ threshold → pass。"""
        from novel import quality_gates as QG
        import novel.generator as G2
        proj = _fake_project(tmp_path, samples_text="手写样例")
        orig = G2.style_radar
        G2.style_radar = lambda project, n, client=None: "报告：\n总相似度：85\n其他细节..."
        try:
            r = QG.check_radar(proj, 1, client=_FakeLLM(), threshold=70)
        finally:
            G2.style_radar = orig
        assert r.passed is True
        assert r.score == 85

    def test_below_threshold_fails(self, tmp_path):
        from novel import quality_gates as QG
        import novel.generator as G2
        proj = _fake_project(tmp_path, samples_text="手写样例")
        orig = G2.style_radar
        G2.style_radar = lambda project, n, client=None: "报告：\n总相似度：50\n..."
        try:
            r = QG.check_radar(proj, 1, client=_FakeLLM(), threshold=70)
        finally:
            G2.style_radar = orig
        assert r.passed is False
        assert r.score == 50


class TestCheckConsistency:
    """check_consistency：依赖 .novel/consistency_report.md，解析「冲突」字段。"""

    def test_no_report_passes(self, tmp_path):
        proj = _fake_project(tmp_path)
        r = check_consistency(proj, client=_FakeLLM())
        assert r.passed is True
        assert "未生成" in r.detail

    def test_zero_conflicts_passes(self, tmp_path):
        proj = _fake_project(tmp_path)
        (proj.novel_dir / "consistency_report.md").write_text(
            "无冲突。一致性良好。", encoding="utf-8",
        )
        r = check_consistency(proj, client=_FakeLLM())
        assert r.passed is True
        assert r.score == 0

    def test_one_conflict_fails(self, tmp_path):
        proj = _fake_project(tmp_path)
        (proj.novel_dir / "consistency_report.md").write_text(
            "冲突：1\n时间线偏移", encoding="utf-8",
        )
        r = check_consistency(proj, client=_FakeLLM())
        assert r.passed is False
        assert r.score == 1


class TestRunAllGates:
    """run_all_gates 聚合：3 种 quality 档 + include_consistency 行为。"""

    def test_draft_only_runs_word_count(self, tmp_path):
        """draft 档：ai_flavor_threshold=None, radar_threshold=None → 只跑 word_count。"""
        from novel.auto_state import AutoSpec, QualityPreset
        spec = AutoSpec(title="t", quality=QualityPreset.DRAFT, target_chapters=1,
                        target_words=3000)
        proj = _fake_project(tmp_path, chapter_text="字" * 3000)
        results = run_all_gates(proj, 1, client=_FakeLLM(), spec=spec)
        assert [r.name for r in results] == ["word_count"]
        assert results[0].passed is True

    def test_standard_word_count_plus_ai(self, tmp_path):
        """standard 档：threshold 数字 → 跑 word + ai。"""
        from novel.auto_state import AutoSpec, QualityPreset
        spec = AutoSpec(title="t", quality=QualityPreset.STANDARD, target_chapters=1,
                        target_words=3000)
        proj = _fake_project(tmp_path, chapter_text="字" * 3000)
        client = _FakeLLM(content="AI 味指数：30")
        results = run_all_gates(proj, 1, client=client, spec=spec)
        names = [r.name for r in results]
        # standard: word + ai；radar 也跑（threshold=60 != None），但 samples 为空跳过检查返回 passed
        # 实际 run_all_gates 看 spec.quality.radar_threshold — STANDARD.radar_threshold=60 != None → 必跑 check_radar
        # 但 check_radar 内部会因没 samples 返回 passed
        assert "word_count" in names
        assert "ai_flavor" in names
        # 验证 ai flavor 实际行为
        ai_result = [r for r in results if r.name == "ai_flavor"][0]
        assert ai_result.passed is True  # 30 < 50

    def test_premium_runs_word_ai_radar_when_samples_exist(self, tmp_path):
        """premium 档 + 有 samples → 跑 word + ai + radar 全 3 个。"""
        from novel.auto_state import AutoSpec, QualityPreset
        import novel.generator as G2
        spec = AutoSpec(title="t", quality=QualityPreset.PREMIUM, target_chapters=1,
                        target_words=3000)
        proj = _fake_project(tmp_path, chapter_text="字" * 3000, samples_text="样例")

        client = _FakeLLM(content="AI 味指数：40")
        orig = G2.style_radar
        G2.style_radar = lambda project, n, client=None: "总相似度：80"
        try:
            results = run_all_gates(proj, 1, client=client, spec=spec)
        finally:
            G2.style_radar = orig
        names = [r.name for r in results]
        assert "word_count" in names
        assert "ai_flavor" in names
        assert "radar" in names
        radar_result = [r for r in results if r.name == "radar"][0]
        assert radar_result.passed is True  # 80 >= 70

    def test_include_consistency_adds_extra_gate(self, tmp_path):
        from novel.auto_state import AutoSpec, QualityPreset
        spec = AutoSpec(title="t", quality=QualityPreset.DRAFT, target_chapters=1,
                        target_words=3000)
        proj = _fake_project(tmp_path, chapter_text="字" * 3000)
        results_no = run_all_gates(proj, 1, client=_FakeLLM(), spec=spec, include_consistency=False)
        results_yes = run_all_gates(proj, 1, client=_FakeLLM(), spec=spec, include_consistency=True)
        assert [r.name for r in results_no] == ["word_count"]
        assert [r.name for r in results_yes] == ["word_count", "consistency"]


class TestSummarize:
    """summarize：返回 (all_passed, failed_list)。"""

    def test_all_passed(self):
        results = [
            GateResult(name="a", passed=True),
            GateResult(name="b", passed=True),
        ]
        all_passed, failed = summarize(results)
        assert all_passed is True
        assert failed == []

    def test_one_failed(self):
        results = [
            GateResult(name="a", passed=True),
            GateResult(name="b", passed=False, detail="bad"),
        ]
        all_passed, failed = summarize(results)
        assert all_passed is False
        assert len(failed) == 1
        assert failed[0].name == "b"

    def test_all_failed(self):
        results = [
            GateResult(name="a", passed=False),
            GateResult(name="b", passed=False),
        ]
        all_passed, failed = summarize(results)
        assert all_passed is False
        assert len(failed) == 2

    def test_empty_results(self):
        all_passed, failed = summarize([])
        assert all_passed is True
        assert failed == []


class TestQualityPresetAllPresets:
    """3 档预设完整字段对比（防止某档 future 改动漏测）。"""

    @pytest.mark.parametrize("preset,expected", [
        (QualityPreset.DRAFT, {"ai_flavor_threshold": None, "radar_threshold": None,
                                  "word_tolerance": 0.3, "max_retries": 1, "iters": 1}),
        (QualityPreset.STANDARD, {"ai_flavor_threshold": 50, "radar_threshold": 60,
                                    "word_tolerance": 0.2, "max_retries": 2, "iters": 3}),
        (QualityPreset.PREMIUM, {"ai_flavor_threshold": 30, "radar_threshold": 70,
                                   "word_tolerance": 0.1, "max_retries": 3, "iters": 3}),
    ])
    def test_preset_thresholds(self, preset, expected):
        assert preset.ai_flavor_threshold == expected["ai_flavor_threshold"]
        assert preset.radar_threshold == expected["radar_threshold"]
        assert preset.word_tolerance == pytest.approx(expected["word_tolerance"])
        assert preset.max_retries == expected["max_retries"]
        assert preset.iters == expected["iters"]