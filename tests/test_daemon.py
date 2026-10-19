"""v0.15+ novel daemon 单测：DRY_RUN 端到端 + criteria 解析 + iteration 终止条件。

覆盖：
  1. criteria 解析（load_criteria）+ LLM 评估器 mock（evaluate_via_llm）
  2. feedback 注入（format_feedback_for_next_iter）
  3. _check_should_stop 终止条件
  4. systemd unit 渲染（render_systemd_unit）
  5. stop signal（is_stop_requested）
  6. _daemon_loop 端到端：mock run_auto_novel + evaluate_via_llm
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from novel import storage as S
from novel.auto_state import AutoSpec, AutoState, Phase, QualityPreset
from novel.criteria import (
    EvaluatorReport,
    CriterionResult,
    _extract_json_block,
    format_feedback_for_next_iter,
    load_criteria,
)
from novel.daemon import (
    _check_should_stop,
    _stop_signal_path,
    is_stop_requested,
    render_systemd_unit,
)
from novel.llm import LLMResult
from novel_cli import app


runner = CliRunner()


# ---------------------------------------------------------------------------
# 1. criteria 解析
# ---------------------------------------------------------------------------

class TestLoadCriteria:
    def test_empty_path_returns_empty(self):
        assert load_criteria("") == []

    def test_nonexistent_file_returns_empty(self, tmp_path):
        assert load_criteria(str(tmp_path / "no.md")) == []

    def test_simple_list(self, tmp_path):
        f = tmp_path / "criteria.md"
        f.write_text("- 第一条\n- 第二条\n- 第三条\n", encoding="utf-8")
        assert load_criteria(f) == ["第一条", "第二条", "第三条"]

    def test_skip_blank_and_header(self, tmp_path):
        f = tmp_path / "criteria.md"
        f.write_text("# 硬指标\n\n- 第一条\n\n## 子节\n- 第二条\n", encoding="utf-8")
        assert load_criteria(f) == ["第一条", "第二条"]

    def test_skip_code_blocks(self, tmp_path):
        f = tmp_path / "criteria.md"
        f.write_text(
            "- 第一条\n"
            "```\n"
            "- 代码块里这条不该被算\n"
            "```\n"
            "- 第二条\n",
            encoding="utf-8",
        )
        assert load_criteria(f) == ["第一条", "第二条"]

    def test_alternative_list_markers(self, tmp_path):
        f = tmp_path / "criteria.md"
        f.write_text("* 一条\n1. 二条\n3. 三条\n", encoding="utf-8")
        assert load_criteria(f) == ["一条", "二条", "三条"]

    def test_plain_text_lines(self, tmp_path):
        f = tmp_path / "criteria.md"
        f.write_text("第一条无标记\n第二条也无标记\n", encoding="utf-8")
        assert load_criteria(f) == ["第一条无标记", "第二条也无标记"]


# ---------------------------------------------------------------------------
# 2. JSON 提取 / 解析
# ---------------------------------------------------------------------------

class TestExtractJsonBlock:
    def test_json_code_block(self):
        text = "```json\n{\"a\": 1}\n```"
        assert _extract_json_block(text) == '{"a": 1}'

    def test_json_in_prose(self):
        text = "分析结果：\n{\"all_passed\": true}\n以上。"
        assert _extract_json_block(text) == '{"all_passed": true}'

    def test_no_json_returns_empty(self):
        assert _extract_json_block("no json here") == ""


# ---------------------------------------------------------------------------
# 3. feedback 注入
# ---------------------------------------------------------------------------

class TestFormatFeedback:
    def test_all_passed_returns_empty(self):
        report = EvaluatorReport(summary="all good", all_passed=True)
        assert format_feedback_for_next_iter(report) == ""

    def test_failed_lists_each_criterion(self):
        report = EvaluatorReport(
            summary="2/3 fail",
            all_passed=False,
            criteria=[
                CriterionResult(id=1, text="第3章不能X", passed=False,
                                evidence="第3章第2段含X", suggestion="删X"),
                CriterionResult(id=2, text="OK", passed=True),
                CriterionResult(id=3, text="第5章≥2500字", passed=False,
                                evidence="实际1800", suggestion="扩展"),
            ],
            top_priority_fixes=["修第3章", "扩第5章"],
        )
        text = format_feedback_for_next_iter(report)
        assert "未通过" in text
        assert "[1]" in text
        assert "[3]" in text
        # 通过的不会列出
        assert "OK" not in text
        # top_priority 列出
        assert "修第3章" in text
        assert "扩第5章" in text


# ---------------------------------------------------------------------------
# 4. 终止条件 _check_should_stop
# ---------------------------------------------------------------------------

class TestCheckShouldStop:
    def test_max_iterations(self, tmp_path):
        should, reason = _check_should_stop(
            tmp_path, iter_count=3, max_iterations=3,
            cost_so_far=0, cost_budget=0,
            started_at=time.time(), max_time_seconds=0,
        )
        assert should is True
        assert "max_iterations" in reason

    def test_cost_budget_exhausted(self, tmp_path):
        should, reason = _check_should_stop(
            tmp_path, iter_count=1, max_iterations=10,
            cost_so_far=10.0, cost_budget=10.0,
            started_at=time.time(), max_time_seconds=0,
        )
        assert should is True
        assert "cost_budget" in reason

    def test_cost_budget_zero_means_unlimited(self, tmp_path):
        should, _ = _check_should_stop(
            tmp_path, iter_count=1, max_iterations=10,
            cost_so_far=99999, cost_budget=0,
            started_at=time.time(), max_time_seconds=0,
        )
        assert should is False

    def test_max_time_exceeded(self, tmp_path):
        should, reason = _check_should_stop(
            tmp_path, iter_count=1, max_iterations=10,
            cost_so_far=0, cost_budget=0,
            started_at=time.time() - 100, max_time_seconds=50,
        )
        assert should is True
        assert "max_time" in reason

    def test_stop_file(self, tmp_path):
        # 用户写 .novel/stop_daemon
        (tmp_path / ".novel").mkdir()
        (_stop_signal_path(tmp_path)).touch()
        should, reason = _check_should_stop(
            tmp_path, iter_count=1, max_iterations=10,
            cost_so_far=0, cost_budget=0,
            started_at=time.time(), max_time_seconds=0,
        )
        assert should is True
        assert "stop_daemon" in reason
        # 验证 stop 文件被消费
        assert not (_stop_signal_path(tmp_path)).exists()

    def test_no_stop_conditions(self, tmp_path):
        should, _ = _check_should_stop(
            tmp_path, iter_count=1, max_iterations=10,
            cost_so_far=1, cost_budget=100,
            started_at=time.time(), max_time_seconds=3600,
        )
        assert should is False


# ---------------------------------------------------------------------------
# 5. systemd unit 渲染
# ---------------------------------------------------------------------------

class TestSystemdUnit:
    def test_renders_project_path(self, tmp_path):
        content = render_systemd_unit(tmp_path)
        assert str(tmp_path.resolve()) in content
        assert "novel_cli.py" in content
        assert "daemon run" in content
        assert "Restart=on-failure" in content

    def test_extra_args_propagate(self, tmp_path):
        content = render_systemd_unit(tmp_path, extra_args="--max-iterations 7")
        assert "--max-iterations 7" in content


# ---------------------------------------------------------------------------
# 6. 端到端：_daemon_loop（mock run_auto_novel + evaluate_via_llm）
# ---------------------------------------------------------------------------

def _fake_project(tmp_path, *, chapter_text="内容", target_words=9000, chapters=3):
    """构造最小可用的 novel 项目（3 章 + 元数据）。

    直接建在 tmp_path 上（而不是子目录），方便 daemon 用 tmp_path 作为 project_dir。
    """
    proj = S.init_project(
        tmp_path, "D", meta={"genre": "现实", "target_words": target_words, "title": "D"},
    )
    for i in range(1, chapters + 1):
        S.save_chapter(proj, i, chapter_text * 100)
    return proj


def _mock_passed_report():
    return EvaluatorReport(
        summary="all 3 pass",
        all_passed=True,
        criteria=[CriterionResult(id=1, text="x", passed=True)],
    )


def _mock_failed_report():
    return EvaluatorReport(
        summary="2/3 fail",
        all_passed=False,
        criteria=[CriterionResult(id=1, text="x", passed=False, suggestion="改")],
        top_priority_fixes=["fix this"],
    )


class _FakeClient:
    """简单 fake，每次 chat_with_continuation 返回 fixed content。"""
    def __init__(self, content="{}"):
        self._result = LLMResult(content=content, model="fake", elapsed_ms=1)
    def chat(self, *a, **k): return self._result
    def chat_with_continuation(self, *a, **k): return self._result


class TestDaemonLoopEndToEnd:
    """Mock run_auto_novel + evaluate_via_llm，验证 daemon 主循环的：
    - 终止条件触发
    - feedback 注入
    - state 保存
    """

    def test_no_criteria_exits_after_one_iter(self, tmp_path, monkeypatch):
        """没 criteria → 跑 1 轮 → 退出。"""
        from novel import daemon as D

        proj = _fake_project(tmp_path)
        spec = AutoSpec(title="D", daemon_criteria_path="", max_iterations=3)

        # Mock run_auto_novel
        iter_count = [0]
        def fake_run(spec_, project_dir, **kwargs):
            iter_count[0] += 1
            return project_dir / "book.md"
        monkeypatch.setattr("novel.auto.run_auto_novel", fake_run)

        # Mock evaluate_via_llm（不应该被调用）
        called = [False]
        def fake_eval(*a, **k):
            called[0] = True
            return _mock_passed_report()
        monkeypatch.setattr(D, "evaluate_via_llm", fake_eval)

        # 关闭 LLMClient 默认实例
        monkeypatch.setattr("novel.criteria.LLMClient", _FakeClient)

        # 关掉 load_global 默认（避免真 .env 影响）

        cfg = type("Cfg", (), {"dry_run": True})()

        state = D._daemon_loop(spec, tmp_path, cfg, max_iterations=3)
        assert iter_count[0] == 1  # 只跑了 1 轮
        assert state.iteration_count == 1
        assert called[0] is False  # 没 criteria 不调评估
        assert state.last_iter_passed is True  # 视为通过

    def test_all_pass_exits_immediately(self, tmp_path, monkeypatch):
        """第一轮评估就全 pass → 立即退出（不进入第二轮）。"""
        from novel import daemon as D

        proj = _fake_project(tmp_path)
        spec = AutoSpec(
            title="D",
            daemon_criteria_path=str(tmp_path / "criteria.md"),
            max_iterations=5,
        )
        (tmp_path / "criteria.md").write_text("- 第一条\n", encoding="utf-8")

        iter_count = [0]
        def fake_run(spec_, project_dir, **kwargs):
            iter_count[0] += 1
            return project_dir / "book.md"
        monkeypatch.setattr("novel.auto.run_auto_novel", fake_run)

        monkeypatch.setattr(D, "evaluate_via_llm", lambda *a, **k: _mock_passed_report())
        monkeypatch.setattr("novel.criteria.LLMClient", _FakeClient)

        cfg = type("Cfg", (), {"dry_run": True})()
        state = D._daemon_loop(spec, tmp_path, cfg, max_iterations=5)
        assert iter_count[0] == 1  # 1 轮就退
        assert state.last_iter_passed is True

    def test_iterates_until_pass(self, tmp_path, monkeypatch):
        """前 2 轮 fail，第 3 轮 pass → 共 3 轮。"""
        from novel import daemon as D

        proj = _fake_project(tmp_path)
        spec = AutoSpec(
            title="D",
            daemon_criteria_path=str(tmp_path / "criteria.md"),
            max_iterations=5,
        )
        (tmp_path / "criteria.md").write_text("- 第一条\n", encoding="utf-8")

        reports_queue = [_mock_failed_report(), _mock_failed_report(), _mock_passed_report()]
        def fake_eval(*a, **k):
            return reports_queue.pop(0)
        iter_count = [0]
        def fake_run(spec_, project_dir, **kwargs):
            iter_count[0] += 1
            return project_dir / "book.md"
        monkeypatch.setattr("novel.auto.run_auto_novel", fake_run)
        monkeypatch.setattr(D, "evaluate_via_llm", fake_eval)
        monkeypatch.setattr("novel.criteria.LLMClient", _FakeClient)

        cfg = type("Cfg", (), {"dry_run": True})()
        state = D._daemon_loop(spec, tmp_path, cfg, max_iterations=5)
        assert iter_count[0] == 3
        assert state.iteration_count == 3
        assert state.last_iter_passed is True

    def test_max_iterations_terminates(self, tmp_path, monkeypatch):
        """max_iterations=2 全 fail → 共 2 轮后退出。"""
        from novel import daemon as D

        proj = _fake_project(tmp_path)
        spec = AutoSpec(
            title="D",
            daemon_criteria_path=str(tmp_path / "criteria.md"),
            max_iterations=2,
        )
        (tmp_path / "criteria.md").write_text("- 一条\n", encoding="utf-8")

        monkeypatch.setattr("novel.auto.run_auto_novel",
                             lambda *a, **k: a[1] / "book.md")
        monkeypatch.setattr(D, "evaluate_via_llm", lambda *a, **k: _mock_failed_report())
        monkeypatch.setattr("novel.criteria.LLMClient", _FakeClient)

        cfg = type("Cfg", (), {"dry_run": True})()
        state = D._daemon_loop(spec, tmp_path, cfg, max_iterations=2)
        assert state.iteration_count == 2
        assert state.last_iter_passed is False

    def test_stop_file_terminates_early(self, tmp_path, monkeypatch):
        """用户在第 1 轮后写 .novel/stop_daemon → 第 2 轮开始时退出。"""
        from novel import daemon as D

        proj = _fake_project(tmp_path)
        spec = AutoSpec(
            title="D",
            daemon_criteria_path=str(tmp_path / "criteria.md"),
            max_iterations=10,
        )
        (tmp_path / "criteria.md").write_text("- 一条\n", encoding="utf-8")

        iter_count = [0]

        def fake_run(spec_, project_dir, **kwargs):
            iter_count[0] += 1
            # 在第 1 轮后写 stop 文件
            if iter_count[0] == 1:
                (_stop_signal_path(project_dir)).touch()
            return project_dir / "book.md"
        monkeypatch.setattr("novel.auto.run_auto_novel", fake_run)
        monkeypatch.setattr(D, "evaluate_via_llm", lambda *a, **k: _mock_failed_report())
        monkeypatch.setattr("novel.criteria.LLMClient", _FakeClient)

        cfg = type("Cfg", (), {"dry_run": True})()
        state = D._daemon_loop(spec, tmp_path, cfg, max_iterations=10)
        # 第 1 轮跑完 + 评估 fail + 写 stop → 第 2 轮 check 时退出
        assert iter_count[0] == 1
        assert state.iteration_count == 1


# ---------------------------------------------------------------------------
# 7. CLI
# ---------------------------------------------------------------------------

class TestDaemonCLI:
    def test_daemon_help(self):
        r = runner.invoke(app, ["daemon", "--help"])
        assert r.exit_code == 0
        assert "run" in r.stdout
        assert "status" in r.stdout
        assert "stop" in r.stdout
        assert "unit" in r.stdout

    def test_daemon_unit_outputs_unit_file(self, tmp_path, monkeypatch):
        proj = _fake_project(tmp_path)
        r = runner.invoke(app, ["daemon", "unit", "--project", str(tmp_path), "--user", "test"])
        assert r.exit_code == 0
        assert "[Unit]" in r.stdout
        assert "ExecStart=" in r.stdout
        assert "Restart=on-failure" in r.stdout
        assert "daemon run" in r.stdout

    def test_daemon_stop_writes_file(self, tmp_path, monkeypatch):
        _fake_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        r = runner.invoke(app, ["daemon", "stop", "--here"])
        assert r.exit_code == 0
        assert (tmp_path / ".novel" / "stop_daemon").exists()

    def test_daemon_status_no_project_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        r = runner.invoke(app, ["daemon", "status", "--here"])
        # 没有 .novel → 报错
        assert r.exit_code != 0
