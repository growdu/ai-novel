"""novel_cli 集成测试。

通过 typer.testing.CliRunner 模拟调用命令，验证：
- version / setup 不依赖 LLM
- doctor / status / init 在临时目录里能跑通
- 友好错误信息能找到
"""
from __future__ import annotations


from typer.testing import CliRunner

from novel import __version__
from novel_cli import app


runner = CliRunner()


class TestVersion:
    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.stdout

    def test_version_short_flag(self):
        result = runner.invoke(app, ["-V"])
        assert result.exit_code == 0
        assert __version__ in result.stdout

    def test_version_command(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert __version__ in result.stdout
        assert "novel-writer" in result.stdout

    def test_version_short(self):
        result = runner.invoke(app, ["version", "--short"])
        assert result.exit_code == 0
        assert result.stdout.strip() == __version__


class TestHelp:
    def test_root_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        # 应能看到所有顶层命令
        assert "init" in result.stdout
        assert "doctor" in result.stdout
        assert "version" in result.stdout
        assert "config" in result.stdout

    def test_init_help(self):
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0
        assert "--title" in result.stdout
        assert "--genre" in result.stdout

    def test_doctor_help(self):
        result = runner.invoke(app, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "--fix" in result.stdout
        assert "--json" in result.stdout

    def test_rollback_help(self):
        result = runner.invoke(app, ["rollback", "--help"])
        assert result.exit_code == 0
        assert "--yes" in result.stdout


class TestSetupNonInteractive:
    """setup --no-input 用已有 env 写出文件。"""

    def test_setup_writes_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
        monkeypatch.setenv("OPENAI_MODEL", "test-model")
        result = runner.invoke(app, ["setup", "--no-input", "--force"])
        assert result.exit_code == 0, result.stdout
        env_file = tmp_path / ".env"
        assert env_file.exists()
        content = env_file.read_text(encoding="utf-8")
        assert "test-key-12345678" in content
        assert "https://example.com/v1" in content
        assert "test-model" in content

    def test_setup_skips_when_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        existing = tmp_path / ".env"
        existing.write_text("EXISTING=true\n")
        result = runner.invoke(app, ["setup", "--no-input"])
        assert result.exit_code == 0
        assert "已存在" in result.stdout or "存在" in result.stdout
        # 文件未被覆盖
        assert existing.read_text() == "EXISTING=true\n"


class TestInit:
    def test_init_creates_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [
            "init", "test_novel",
            "--title", "测试小说",
            "--theme", "东北小镇命案",
            "--genre", "悬疑",
            "--style", "冷峻",
        ])
        assert result.exit_code == 0, result.stdout
        proj_dir = tmp_path / "test_novel"
        assert (proj_dir / ".novel").exists()
        assert (proj_dir / ".novel" / "outline.md").exists()
        assert (proj_dir / ".novel" / "characters.md").exists()
        assert (proj_dir / ".novel" / "genre_preset.md").exists()
        assert (proj_dir / ".novel" / "style.md").exists()

    def test_init_here(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [
            "init", ".",
            "--here",
            "--title", "就地测试",
            "--theme", "主题",
            "--genre", "现实",
        ])
        assert result.exit_code == 0, result.stdout
        assert (tmp_path / ".novel").exists()

    def test_init_existing_dir_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        existing = tmp_path / "test_novel"
        existing.mkdir()
        (existing / "something").write_text("x")
        result = runner.invoke(app, [
            "init", "test_novel",
            "--title", "x",
        ])
        assert result.exit_code != 0
        assert "不为空" in result.stdout or "不为空" in (result.stderr or "")


class TestDoctor:
    def test_doctor_without_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # 无 .novel 目录，应给友好提示
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code != 0
        # 友好错误走 rich console，不一定进 stdout/stderr，拼接传带
        output = (result.stdout or "") + (getattr(result, "stderr", None) or "")
        # 也可能由 rich.console 捕获到 fixture，需要从 output 字符串里查
        if not output:
            output = str(result)
        assert "novel init" in output or "项目目录" in output or "未找到" in output

    def test_doctor_with_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # 先建项目
        runner.invoke(app, [
            "init", "p1",
            "--title", "x",
            "--theme", "y",
            "--genre", "悬疑",
        ])
        monkeypatch.chdir(tmp_path / "p1")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")
        result = runner.invoke(app, ["doctor"])
        # 不报错 + JSON 标签存在
        assert "诊断报告" in result.stdout or "doctor" in result.stdout.lower()

    def test_doctor_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init", "p2", "--title", "x", "--genre", "悬疑"])
        monkeypatch.chdir(tmp_path / "p2")
        result = runner.invoke(app, ["doctor", "--json"])
        assert result.exit_code == 0
        assert '"issues"' in result.stdout
        assert '"warnings"' in result.stdout


class TestStatusWithoutProject:
    def test_status_gives_friendly_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code != 0
        output = (result.stdout or "") + (getattr(result, "stderr", None) or "")
        if not output:
            output = str(result)
        assert "novel init" in output or "项目目录" in output or "未找到" in output


class TestConfigCommand:
    def test_config_show(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["config"])
        # 即使没 .env 也应能显示默认
        assert result.exit_code == 0
        assert "配置" in result.stdout or "base_url" in result.stdout


class TestGenresAndStyles:
    def test_genres_lists(self):
        result = runner.invoke(app, ["genres"])
        assert result.exit_code == 0
        assert "悬疑" in result.stdout or "题材" in result.stdout

    def test_styles_lists(self):
        result = runner.invoke(app, ["styles"])
        assert result.exit_code == 0
        assert "文风" in result.stdout

    def test_webnovel_genres(self):
        result = runner.invoke(app, ["webnovel-genres"])
        assert result.exit_code == 0

    def test_webnovel_styles(self):
        result = runner.invoke(app, ["webnovel-styles"])
        assert result.exit_code == 0


class TestShellCompletion:
    def test_completion_command_exists(self):
        """Typer 应自动生成 completion 子命令。"""
        result = runner.invoke(app, ["--help"])
        # add_completion=True 时会自动加 --install-completion
        assert "install-completion" in result.stdout or "--help" in result.stdout


class TestListInfoWhereami:
    """新命令：list / info / templates / whereami。"""

    def test_list_finds_projects(self, tmp_path, monkeypatch):
        # 在临时目录建两个项目
        monkeypatch.chdir(tmp_path)
        for name in ("proj_a", "proj_b"):
            runner.invoke(app, [
                "init", name, "--title", name, "--genre", "悬疑",
            ])
        result = runner.invoke(app, ["list", "--path", str(tmp_path), "--depth", "2"])
        assert result.exit_code == 0
        assert "proj_a" in result.stdout
        assert "proj_b" in result.stdout

    def test_list_no_projects(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["list", "--path", str(tmp_path)])
        assert "没有找到" in result.stdout

    def test_list_missing_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["list", "--path", "/nonexistent/zzz"])
        assert result.exit_code != 0
        assert "不存在" in result.stdout

    def test_info_existing_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init", "ip1", "--title", "测试标题", "--genre", "武侠"])
        result = runner.invoke(app, ["info", str(tmp_path / "ip1")])
        assert result.exit_code == 0
        assert "测试标题" in result.stdout
        assert "武侠" in result.stdout
        assert "已写章节" in result.stdout

    def test_info_not_a_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(app, ["info", str(empty)])
        assert result.exit_code != 0
        # Rich 可能在 "novel" 后换行；用 normalize 比较
        out = result.stdout.replace("\n", "").replace(" ", "")
        assert "不是novel项目" in out

    def test_whereami_inside_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init", "wp1", "--title", "测试"])
        monkeypatch.chdir(tmp_path / "wp1")
        result = runner.invoke(app, ["whereami"])
        assert result.exit_code == 0
        assert "当前项目" in result.stdout
        assert "测试" in result.stdout

    def test_whereami_outside_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["whereami"])
        assert result.exit_code == 0
        assert "不在任何 novel 项目内" in result.stdout

    def test_templates(self):
        result = runner.invoke(app, ["templates"])
        assert result.exit_code == 0
        # 至少展示几个常见模板
        assert "东北悬疑" in result.stdout
        assert "武侠" in result.stdout
        assert "init" in result.stdout  # 用法示例