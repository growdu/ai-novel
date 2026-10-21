"""novel.auto_state 测试：序列化、续跑、原子写。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel.auto_state import (
    AutoSpec,
    AutoState,
    ChapterResult,
    Phase,
    QualityPreset,
)


class TestPhase:
    def test_values(self):
        assert Phase.PLANNING.value == "planning"
        assert Phase.WRITING.value == "writing"
        assert Phase.DONE.value == "done"


class TestQualityPreset:
    def test_premium_thresholds(self):
        p = QualityPreset.PREMIUM
        assert p.iters == 3
        assert p.word_tolerance == pytest.approx(0.1)
        assert p.ai_flavor_threshold == 30
        assert p.radar_threshold == 70
        assert p.max_retries == 3

    def test_draft_skips_optional_checks(self):
        p = QualityPreset.DRAFT
        assert p.iters == 1
        assert p.word_tolerance == pytest.approx(0.3)
        assert p.ai_flavor_threshold is None
        assert p.radar_threshold is None
        assert p.max_retries == 1

    def test_standard_balanced(self):
        p = QualityPreset.STANDARD
        # 3 轮（曾为 2）：实测 2 轮时模型写不到字数下限（均 2034–2329 vs 下限 2400）
        assert p.iters == 3
        assert p.word_tolerance == pytest.approx(0.2)
        assert p.ai_flavor_threshold == 50
        assert p.radar_threshold == 60
        assert p.max_retries == 2


class TestAutoSpec:
    def test_chapters_auto(self):
        s = AutoSpec(title="x", theme="t", target_words=60000)
        assert s.target_chapters == 20  # 60000 // 3000

    def test_explicit_chapters(self):
        s = AutoSpec(title="x", theme="t", target_words=60000, target_chapters=10)
        assert s.target_chapters == 10
        # 60000 / 10 = 6000
        assert s.per_chapter_words == 6000

    def test_per_chapter_min_2000(self):
        s = AutoSpec(title="x", theme="t", target_words=10000, target_chapters=100)
        assert s.per_chapter_words >= 2000  # 10000/100 = 100, 但强制最小 2000


class TestChapterResult:
    def test_defaults(self):
        r = ChapterResult(chapter_no=1)
        assert r.status == "pending"
        assert r.word_count == 0
        assert r.ai_flavor is None
        assert r.error == ""


class TestAutoState:
    def test_to_dict_round_trip(self):
        s = AutoState(
            spec={"title": "x", "quality": "premium"},
            phase=Phase.WRITING,
            chapters_total=10,
            chapters_done=[1, 2, 3],
            chapters_failed=[2],
            chapter_results={1: ChapterResult(chapter_no=1, status="generated", word_count=3000)},
            cumulative_tokens=12345,
        )
        d = s.to_dict()
        s2 = AutoState.from_dict(d)
        assert s2.spec == {"title": "x", "quality": "premium"}
        assert s2.phase == Phase.WRITING
        assert s2.chapters_total == 10
        assert s2.chapters_done == [1, 2, 3]
        assert s2.chapters_failed == [2]
        assert s2.chapter_results[1].word_count == 3000
        assert s2.cumulative_tokens == 12345

    def test_atomic_save_load(self, tmp_path):
        s = AutoState(spec={"title": "x"}, phase=Phase.PLANNING, chapters_total=5)
        s.save(tmp_path)
        s2 = AutoState.load(tmp_path)
        assert s2 is not None
        assert s2.phase == Phase.PLANNING
        assert s2.chapters_total == 5

    def test_load_missing_returns_none(self, tmp_path):
        assert AutoState.load(tmp_path) is None

    def test_load_corrupted_returns_none(self, tmp_path):
        (tmp_path / ".novel").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".novel" / "auto_state.json").write_text("not json{", encoding="utf-8")
        assert AutoState.load(tmp_path) is None

    def test_clear(self, tmp_path):
        s = AutoState(spec={"title": "x"})
        s.save(tmp_path)
        AutoState.clear(tmp_path)
        assert AutoState.load(tmp_path) is None

    def test_progress_ratio(self):
        s = AutoState(chapters_total=10, chapters_done=[1, 2, 3])
        assert s.progress_ratio == pytest.approx(0.3)
        s2 = AutoState(chapters_total=0)
        assert s2.progress_ratio == 0.0

    def test_total_words(self):
        s = AutoState(chapter_results={
            1: ChapterResult(chapter_no=1, word_count=100),
            2: ChapterResult(chapter_no=2, word_count=200),
        })
        assert s.total_words == 300

    def test_mark_chapter_done(self):
        s = AutoState()
        s.mark_chapter_done(ChapterResult(chapter_no=1, status="generated"))
        assert 1 in s.chapters_done
        assert s.chapter_results[1].status == "generated"
        # 失败也记
        s.mark_chapter_done(ChapterResult(chapter_no=2, status="failed"))
        assert 2 in s.chapters_failed
        # 重复添加不重复
        s.mark_chapter_done(ChapterResult(chapter_no=2, status="generated"))
        assert s.chapters_done.count(2) == 1

    def test_is_chapter_done(self):
        s = AutoState(chapters_done=[1, 2], chapters_failed=[3])
        assert s.is_chapter_done(1)
        assert s.is_chapter_done(3) is False  # failed ≠ done
        assert s.is_chapter_done(99) is False

    def test_estimate_remaining(self):
        s = AutoState(chapters_total=10, chapters_done=[1, 2, 3])
        assert s.estimate_remaining_chapters() == 7