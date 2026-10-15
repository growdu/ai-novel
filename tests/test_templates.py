"""novel.templates 单元测试 + novel init --template 集成测试。"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from novel.templates import TEMPLATES, list_templates, get_template, apply_template, Template
from novel_cli import app


runner = CliRunner()


class TestTemplates:
    def test_list_templates_returns_at_least_10(self):
        tpls = list_templates()
        assert len(tpls) >= 10

    def test_get_template_exact(self):
        t = get_template("东北悬疑")
        assert t is not None
        assert t.genre == "悬疑"
        assert t.style == "冷峻"

    def test_get_template_partial_match(self):
        # "东北" 部分匹配到 "东北悬疑"
        t = get_template("东北")
        assert t is not None
        assert "东北" in t.name

    def test_get_template_tag_match(self):
        t = get_template("双雪涛")
        assert t is not None
        assert "东北悬疑" in t.name

    def test_get_template_description_match(self):
        t = get_template("金庸")
        assert t is not None
        assert "武侠" in t.name

    def test_get_template_unknown_returns_none(self):
        assert get_template("完全不存在的模板xyz") is None

    def test_get_template_empty_returns_none(self):
        assert get_template("") is None

    def test_apply_template_returns_defaults(self):
        t = get_template("东北悬疑")
        values = apply_template(t)
        assert values["genre"] == "悬疑"
        assert values["style"] == "冷峻"
        assert values["words"] == 80000
        assert "盘锦往事" in values["title"]

    def test_apply_template_overrides(self):
        t = get_template("东北悬疑")
        values = apply_template(t, overrides={"title": "我的新书", "words": 100000})
        assert values["title"] == "我的新书"
        assert values["words"] == 100000
        assert values["genre"] == "悬疑"  # 未覆盖

    def test_apply_template_none_overrides_use_defaults(self):
        """None 值应视为未指定，回退到模板默认（之前 bug 会返回 None）。"""
        t = get_template("东北悬疑")
        values = apply_template(t, overrides={"title": None, "genre": None, "words": None})
        assert values["title"] == "盘锦往事"  # 模板默认
        assert values["genre"] == "悬疑"      # 模板默认（不是 None）
        assert values["words"] == 80000       # 模板默认（不是 None）

    def test_template_has_required_fields(self):
        for t in TEMPLATES:
            assert t.name, f"模板 {t.name} 没有 name"
            assert t.genre, f"模板 {t.name} 没有 genre"
            assert t.style, f"模板 {t.name} 没有 style"
            assert t.default_words > 0, f"模板 {t.name} 字数 <= 0"
            assert t.description, f"模板 {t.name} 没有 description"


class TestInitWithTemplate:
    def test_init_help_shows_template(self):
        result = runner.invoke(app, ["init", "--help"])
        assert "--template" in result.stdout or "-T" in result.stdout

    def test_init_with_template(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [
            "init", "demo",
            "--template", "东北悬疑",
            "--title", "我的东北故事",
        ])
        assert result.exit_code == 0, result.stdout
        assert "东北悬疑" in result.stdout  # 显示用了模板
        # 项目元数据应正确写入，标题覆盖了模板默认
        proj_yaml = tmp_path / "demo" / ".novel" / "project.yaml"
        assert proj_yaml.exists()
        import yaml
        data = yaml.safe_load(proj_yaml.read_text(encoding="utf-8"))
        assert data["title"] == "我的东北故事"
        assert data["genre"] == "悬疑"  # 模板默认被应用
        assert data["target_words"] == 80000  # 模板默认字数

    def test_init_with_unknown_template_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [
            "init", "demo",
            "--template", "不存在的模板",
            "--title", "x",
        ])
        assert result.exit_code != 0
        assert "未知模板" in result.stdout

    def test_init_with_template_partial_name(self, tmp_path, monkeypatch):
        """模糊匹配：'东北' → 东北悬疑。"""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [
            "init", "demo",
            "--template", "东北",
            "--title", "x",
        ])
        assert result.exit_code == 0, result.stdout
        assert "东北悬疑" in result.stdout

    def test_init_with_template_partial_words(self, tmp_path, monkeypatch):
        """--words 100000 覆盖模板默认 80000。"""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [
            "init", "demo",
            "--template", "东北悬疑",
            "--title", "x",
            "--words", "100000",
        ])
        assert result.exit_code == 0, result.stdout
        # project.yaml 应该存 100000
        import yaml
        proj_yaml = tmp_path / "demo" / ".novel" / "project.yaml"
        data = yaml.safe_load(proj_yaml.read_text(encoding="utf-8"))
        assert data["target_words"] == 100000