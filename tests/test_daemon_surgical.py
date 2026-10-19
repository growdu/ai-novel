"""v0.16+ surgical rebuild 测试。

覆盖：
  1. criteria.EvaluatorReport.failed_chapters 字段 + _parse_report 提取
  2. run_auto_novel(only_chapters=[N]) 跳过其他章（state 标 done；out 是 book.md）
  3. daemon 主循环第 1 轮全跑、第 2 轮 surgical（mock run_auto_novel 看 only_chapters 参数）
  4. passed_chapters 累加逻辑
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from novel import storage as S
from novel.auto_state import AutoSpec, AutoState, QualityPreset
from novel.criteria import (
    CriterionResult,
    EvaluatorReport,
    _parse_report,
)
from novel.llm import LLMResult
from novel_cli import app


runner = CliRunner()


# ---------------------------------------------------------------------------
# 1. failed_chapters 字段
# ---------------------------------------------------------------------------

class TestFailedChaptersField:
    def test_default_empty(self):
        r = EvaluatorReport(summary="x", all_passed=True)
        assert r.failed_chapters == []

    def test_to_dict_includes_field(self):
        r = EvaluatorReport(summary="x", all_passed=False, failed_chapters=[3, 7])
        d = r.to_dict()
        assert d["failed_chapters"] == [3, 7]

    def test_parse_report_extracts_int_list(self):
        parsed = {
            "summary": "x",
            "all_passed": False,
            "criteria": [],
            "failed_chapters": [12, 3, 7],  # 乱序
        }
        r = _parse_report(parsed)
        # 应排序去重
        assert r.failed_chapters == [3, 7, 12]

    def test_parse_report_handles_non_int(self):
        parsed = {
            "summary": "x", "all_passed": False, "criteria": [],
            "failed_chapters": [1, "abc", 2, None, 3],
        }
        r = _parse_report(parsed)
        assert r.failed_chapters == [1, 2, 3]

    def test_parse_report_missing_field_is_empty(self):
        parsed = {"summary": "x", "all_passed": True, "criteria": []}
        r = _parse_report(parsed)
        assert r.failed_chapters == []


# ---------------------------------------------------------------------------
# 2. run_auto_novel(only_chapters=[N]) 跳过其他章
# ---------------------------------------------------------------------------

class TestRunAutoNovelOnlyChapters:
    """v0.16+ only_chapters：只重写指定章，其他视为已通过。"""

    def _build_project(self, tmp_path, *, target_chapters=5):
        proj = S.init_project(
            tmp_path, "T", meta={"genre": "现实", "target_words": 5000, "title": "T"},
        )
        for i in range(1, target_chapters + 1):
            S.save_chapter(proj, i, "内容" * 50)
        return proj

    def test_no_only_chapters_writes_all(self, tmp_path, monkeypatch):
        from novel.auto import run_auto_novel
        proj = self._build_project(tmp_path, target_chapters=3)
        spec = AutoSpec(title="T", target_words=5000, target_chapters=3,
                        quality=QualityPreset.DRAFT)

        # DRY_RUN 走 LLMClient 内部的 _dry_run 路径（无需真 API）
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")

        out = run_auto_novel(spec, tmp_path, only_chapters=None)
        # DRY_RUN 仍会跑 _planning_phase（需要 outline）→ 写所有 3 章
        assert out.exists()

    def test_only_chapters_skips_others(self, tmp_path, monkeypatch):
        """only_chapters=[2] 时第 1/3 章视为已通过，state 标 done。"""
        from novel.auto import run_auto_novel

        proj = self._build_project(tmp_path, target_chapters=3)
        spec = AutoSpec(title="T", target_words=5000, target_chapters=3,
                        quality=QualityPreset.DRAFT)
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")

        # 跑 surgical：只重写第 2 章
        run_auto_novel(spec, tmp_path, only_chapters=[2])

        state = AutoState.load(tmp_path)
        # 全部 3 章都标 done（含 surgical 跳过的）
        assert sorted(state.chapters_done) == [1, 2, 3]


# ---------------------------------------------------------------------------
# 3. daemon 主循环 surgical 调度
# ---------------------------------------------------------------------------

class TestDaemonSurgicalLoop:
    """验证 daemon 状态机：
    - 第 1 轮：only_chapters=None（全跑）
    - 第 2 轮起：only_chapters=failed_chapters（surgical）
    - 累加 passed_chapters
    """

    def _setup_project(self, tmp_path, *, chapters=5):
        proj = S.init_project(
            tmp_path, "T", meta={"genre": "现实", "target_words": 10000, "title": "T"},
        )
        for i in range(1, chapters + 1):
            S.save_chapter(proj, i, "内容" * 50)
        return proj

    def test_first_iteration_runs_full(self, tmp_path, monkeypatch):
        from novel import daemon as D

        self._setup_project(tmp_path, chapters=4)
        spec = AutoSpec(title="T", target_words=10000, target_chapters=4,
                        quality=QualityPreset.DRAFT,
                        daemon_criteria_path="")

        captured_only = []

        def fake_run(spec_, project_dir, **kwargs):
            captured_only.append(kwargs.get("only_chapters"))
            return project_dir / "book.md"

        monkeypatch.setattr("novel.auto.run_auto_novel", fake_run)
        monkeypatch.setattr(D, "evaluate_via_llm", lambda *a, **k: _mock_passed_report())
        monkeypatch.setattr("novel.criteria.LLMClient", _FakeLLM)

        cfg = type("Cfg", (), {"dry_run": True})()
        D._daemon_loop(spec, tmp_path, cfg, max_iterations=3)
        # 第 1 轮：only_chapters=None（全跑）
        assert captured_only[0] is None

    def test_second_iteration_surgical(self, tmp_path, monkeypatch):
        """第 1 轮评估返 [3, 5] failed → 第 2 轮 only_chapters=[3, 5]。"""
        from novel import daemon as D

        self._setup_project(tmp_path, chapters=5)
        spec = AutoSpec(title="T", target_words=10000, target_chapters=5,
                        quality=QualityPreset.DRAFT,
                        daemon_criteria_path=str(tmp_path / "c.md"))
        (tmp_path / "c.md").write_text("- 硬指标\n", encoding="utf-8")

        # 第 1 轮：返 failed=[3, 5]；第 2 轮：返 pass
        eval_calls = [0]
        def fake_eval(*a, **k):
            eval_calls[0] += 1
            if eval_calls[0] == 1:
                return EvaluatorReport(
                    summary="2 fail", all_passed=False,
                    criteria=[CriterionResult(id=1, text="x", passed=False)],
                    failed_chapters=[3, 5],
                )
            return _mock_passed_report()

        captured_only = []

        def fake_run(spec_, project_dir, **kwargs):
            captured_only.append(kwargs.get("only_chapters"))
            return project_dir / "book.md"

        monkeypatch.setattr("novel.auto.run_auto_novel", fake_run)
        monkeypatch.setattr(D, "evaluate_via_llm", fake_eval)
        monkeypatch.setattr("novel.criteria.LLMClient", _FakeLLM)

        cfg = type("Cfg", (), {"dry_run": True})()
        D._daemon_loop(spec, tmp_path, cfg, max_iterations=5)

        # 第 1 轮：None（全跑）
        # 第 2 轮：[3, 5]（surgical 只重写 failed）
        assert captured_only[0] is None
        assert captured_only[1] == [3, 5]

        # passed_chapters 应累加
        state = AutoState.load(tmp_path)
        # 第 1 轮：pass=[1,2,4] (除3,5)
        # 第 2 轮：pass=全集（5 章）→ passed_chapters=[1,2,3,4,5]
        assert state.passed_chapters == [1, 2, 3, 4, 5]

    def test_third_iteration_empty_only_chapters(self, tmp_path, monkeypatch):
        """第 3 轮若 all passed → only_chapters=[]（surgical 空集合，不重写任何章）。"""
        from novel import daemon as D

        self._setup_project(tmp_path, chapters=3)
        spec = AutoSpec(title="T", target_words=5000, target_chapters=3,
                        quality=QualityPreset.DRAFT,
                        daemon_criteria_path=str(tmp_path / "c.md"))
        (tmp_path / "c.md").write_text("- 硬指标\n", encoding="utf-8")

        # 第 1 轮：fail=[2]；第 2 轮：pass
        eval_calls = [0]
        def fake_eval(*a, **k):
            eval_calls[0] += 1
            if eval_calls[0] == 1:
                return EvaluatorReport(
                    summary="1 fail", all_passed=False,
                    criteria=[CriterionResult(id=1, text="x", passed=False)],
                    failed_chapters=[2],
                )
            return _mock_passed_report()

        captured_only = []
        def fake_run(spec_, project_dir, **kwargs):
            captured_only.append(kwargs.get("only_chapters"))
            return project_dir / "book.md"

        monkeypatch.setattr("novel.auto.run_auto_novel", fake_run)
        monkeypatch.setattr(D, "evaluate_via_llm", fake_eval)
        monkeypatch.setattr("novel.criteria.LLMClient", _FakeLLM)

        cfg = type("Cfg", (), {"dry_run": True})()
        D._daemon_loop(spec, tmp_path, cfg, max_iterations=5)

        # 第 1 轮：None
        # 第 2 轮：[2]
        assert captured_only[0] is None
        assert captured_only[1] == [2]
        # 第 3 轮不会跑（all_passed=True → 退出）


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_passed_report():
    return EvaluatorReport(
        summary="all 3 pass",
        all_passed=True,
        criteria=[CriterionResult(id=1, text="x", passed=True)],
    )


class _FakeLLM:
    def __init__(self, content="{}"):
        self._result = LLMResult(content=content, model="fake", elapsed_ms=1)
    def chat(self, *a, **k): return self._result
    def chat_with_continuation(self, *a, **k): return self._result
