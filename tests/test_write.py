"""novel.write 顶层统一入口测试：DRY_RUN 模式覆盖两条工作流分支。"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from novel.auto_state import AutoState, Phase
from novel_cli import app


runner = CliRunner()


@pytest.fixture
def dry_run_env(monkeypatch):
    """DRY_RUN 模式 + 测试 API key。"""
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")
    yield


@pytest.fixture
def source_txt(tmp_path):
    """写一个最简源小说文本用于模仿驱动。"""
    src = tmp_path / "白夜行.txt"
    src.write_text(
        "这是一部关于少年男女在暗黑童年阴影下走上的截然相反道路的作品。"
        "桐原亮司在废弃大楼中为救西本文代而死，西本雪穗继续以优雅姿态攀升。"
        "故事跨越二十年，三个家庭、三代人，围绕一起命案的余波展开。",
        encoding="utf-8",
    )
    return src


class TestWriteDemand:
    """需求驱动：--title 一行到底。"""

    def test_write_requires_title_or_source(self, tmp_path, monkeypatch, dry_run_env):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["write", "demo"])
        # 既没 --title 也没 --from-source → 报错
        assert result.exit_code != 0
        assert "请指定输入" in result.stdout or "--title" in result.stdout

    def test_write_title_overrides_derived_when_source_given(self, tmp_path, monkeypatch, source_txt, dry_run_env):
        """--from-source + --title：--title 覆盖自动派生的标题。"""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [
            "write", "demo",
            "--from-source", str(source_txt),
            "--title", "我自定义的标题",
            "--direction", "换壳",
            "--genre", "校园",
            "--style", "冷峻",
            "--words", "9000",
            "--chapters", "2",
            "--quality", "draft",
        ])
        assert result.exit_code == 0, result.stdout
        import yaml
        data = yaml.safe_load((tmp_path / "demo" / ".novel" / "project.yaml").read_text(encoding="utf-8"))
        assert data["title"] == "我自定义的标题"

    def test_write_demand_end_to_end(self, tmp_path, monkeypatch, dry_run_env):
        """novel write demo --title X --theme Y 一行跑完 6 阶段。"""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [
            "write", "demo",
            "--title", "DRY_RUN 需求驱动测试",
            "--theme", "测试主题",
            "--genre", "悬疑",
            "--style", "冷峻",
            "--words", "9000",
            "--chapters", "3",
            "--quality", "draft",
        ])
        assert result.exit_code == 0, result.stdout
        # 项目应建出来
        project = tmp_path / "demo"
        assert (project / ".novel" / "project.yaml").exists()
        # auto_state 应到 DONE
        state = AutoState.load(project)
        assert state is not None
        assert state.phase == Phase.DONE
        assert len(state.chapters_done) == 3
        # book.md 应产出
        book = project / "book.md"
        assert book.exists()


class TestWriteAdapt:
    """模仿驱动：--from-source 提骨架 → 改编 → 直接进 auto。"""

    def test_write_adapt_unknown_source(self, tmp_path, monkeypatch, dry_run_env):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [
            "write", "fanfic",
            "--from-source", "不存在的文件.txt",
            "--direction", "换壳",
        ])
        assert result.exit_code != 0
        assert "不存在" in result.stdout

    def test_write_adapt_end_to_end(self, tmp_path, monkeypatch, source_txt, dry_run_env):
        """novel write demo --from-source 白夜行.txt --direction 换壳 一行到底。"""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [
            "write", "fanfic",
            "--from-source", str(source_txt),
            "--direction", "换名 + 换壳",
            "--genre", "校园",
            "--style", "冷峻",
            "--words", "9000",
            "--chapters", "3",
            "--quality", "draft",
            "--title", "冬夜的灰",
        ])
        assert result.exit_code == 0, result.stdout
        project = tmp_path / "fanfic"
        # adapt.md 应保存了骨架 + 改编方案
        adapt = project / ".novel" / "adapt.md"
        assert adapt.exists()
        # 自动写入的 outline.md 应包含模仿改编内容
        outline = project / ".novel" / "outline.md"
        assert outline.exists()
        assert "模仿改编" in outline.read_text(encoding="utf-8")
        # auto_state 应到 DONE
        state = AutoState.load(project)
        assert state is not None
        assert state.phase == Phase.DONE
        # book.md 应产出
        assert (project / "book.md").exists()


class TestWriteHelp:
    """CLI 帮助与互斥验证。"""

    def test_write_help_shows_two_modes(self):
        result = runner.invoke(app, ["write", "--help"])
        assert result.exit_code == 0
        assert "--title" in result.stdout
        assert "--from-source" in result.stdout
        assert "--direction" in result.stdout
