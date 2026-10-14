"""两阶段工作流测试：plan-all / plans / auto --plans-only。"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from novel_cli import app


runner = CliRunner()


@pytest.fixture
def init_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, [
        "init", "demo", "--title", "测试",
        "--theme", "主题", "--genre", "悬疑", "--style", "冷峻",
        "--words", "9000",  # 3 章
    ])
    assert result.exit_code == 0, result.stdout
    monkeypatch.chdir(tmp_path / "demo")
    return tmp_path / "demo"


class TestPlanAll:
    def test_plan_all_help(self):
        result = runner.invoke(app, ["plan-all", "--help"])
        assert result.exit_code == 0
        assert "--refresh" in result.stdout
        assert "--end" in result.stdout

    def test_plan_all_no_outline_yet(self, init_project):
        # 没有 outline，直接 plan-all 应该提示先生成大纲
        result = runner.invoke(app, ["plan-all"])
        # 出现 "0" 或 "未生成" 之类提示
        assert result.exit_code == 0  # 不崩

    def test_plan_all_after_outline(self, init_project, monkeypatch):
        # 写一个简单的 outline 文件（模拟）
        from novel.config import load_global
        init_project.mkdir(parents=True, exist_ok=True)
        (init_project / ".novel" / "outline.md").write_text(
            "**第一章 开端**\n主角出场\n\n**第二章 发展**\n冲突初现\n\n**第三章 高潮**\n决战\n",
            encoding="utf-8",
        )
        # 没设 API key 时只测结构（DRY_RUN 应该可以）
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        result = runner.invoke(app, ["plan-all"])
        assert result.exit_code == 0, result.stdout


class TestPlans:
    def test_plans_help(self):
        result = runner.invoke(app, ["plans", "--help"])
        assert result.exit_code == 0
        assert "--refresh" in result.stdout

    def test_plans_no_plans_yet(self, init_project):
        result = runner.invoke(app, ["plans"])
        assert result.exit_code == 0
        assert "没有" in result.stdout or "plan-all" in result.stdout

    def test_plans_refresh_requires_no(self, init_project):
        result = runner.invoke(app, ["plans", "--refresh"])
        assert result.exit_code != 0

    def test_plans_specific_chapter(self, init_project):
        # 写一个 fake 章纲
        plans_dir = init_project / ".novel" / "chapter_plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        (plans_dir / "0001.md").write_text(
            "# 第 1 章细化大纲\n\n场景 1。\n场景 2。",
            encoding="utf-8",
        )
        result = runner.invoke(app, ["plans", "1"])
        assert result.exit_code == 0
        assert "场景 1" in result.stdout

    def test_plans_list(self, init_project):
        plans_dir = init_project / ".novel" / "chapter_plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        for n in (1, 2, 3):
            (plans_dir / f"{n:04d}.md").write_text(
                f"# 第 {n} 章细化大纲\n\n第 {n} 章场景规划内容",
                encoding="utf-8",
            )
        result = runner.invoke(app, ["plans"])
        assert result.exit_code == 0
        assert "0001" in result.stdout or "1" in result.stdout
        # 应有 3 章标记
        assert "3" in result.stdout


class TestAutoPlansOnly:
    def test_auto_plans_only_flag_exists(self):
        result = runner.invoke(app, ["auto", "--help"])
        assert result.exit_code == 0
        assert "--plans-only" in result.stdout
        assert "--skip-plans" in result.stdout