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


import pytest