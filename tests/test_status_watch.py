"""novel status --watch 测试。"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from novel_cli import app


runner = CliRunner()


class TestStatusWatch:
    def test_status_help_shows_watch(self):
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0
        assert "--watch" in result.stdout
        assert "--auto" in result.stdout

    def test_status_without_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code != 0

    def test_status_basic(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, [
            "init", "demo", "--title", "测试", "--genre", "悬疑",
        ])
        monkeypatch.chdir(tmp_path / "demo")
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "测试" in result.stdout

    def test_status_auto_only_no_state(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, [
            "init", "demo", "--title", "x", "--genre", "悬疑",
        ])
        monkeypatch.chdir(tmp_path / "demo")
        result = runner.invoke(app, ["status", "--auto"])
        assert result.exit_code == 0
        assert "未运行" in result.stdout or "未启动" in result.stdout