"""novel.diff_utils + novel.config 单元测试。"""
from __future__ import annotations



from novel import diff_utils
from novel.config import (
    GlobalConfig,
    _env_bool,
    _env_float,
    _env_int,
    find_project_root,
)


class TestUnifiedDiff:
    def test_no_diff_returns_empty(self):
        text = "line1\nline2\nline3"
        assert diff_utils.unified_diff(text, text) == ""

    def test_simple_addition(self):
        old = "a\nb\nc"
        new = "a\nb\nc\nd"
        diff = diff_utils.unified_diff(old, new)
        assert "+d" in diff
        assert "-a" not in diff  # 旧的不变

    def test_unified_diff_handles_empty(self):
        assert diff_utils.unified_diff("", "new content") != ""


class TestStatsDiff:
    def test_identical(self):
        s = diff_utils.stats_diff("a\nb", "a\nb")
        assert s["added"] == 0
        assert s["removed"] == 0
        assert s["same"] == 2
        assert s["similarity"] == 1.0

    def test_fully_different(self):
        s = diff_utils.stats_diff("a", "b")
        assert s["same"] == 0
        assert s["added"] == 1
        assert s["removed"] == 1
        assert s["similarity"] == 0.0

    def test_empty_inputs(self):
        s = diff_utils.stats_diff("", "")
        assert s["similarity"] == 1.0


class TestGlobalConfig:
    def test_default_values(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = GlobalConfig()
        assert cfg.api_key == ""
        assert cfg.temperature == 0.9
        assert cfg.top_p == 0.95
        assert cfg.max_tokens == 4096
        assert cfg.target_chapter_words == 3000
        assert cfg.dry_run is False

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")
        monkeypatch.setenv("TEMPERATURE", "0.5")
        monkeypatch.setenv("DRY_RUN", "true")
        cfg = GlobalConfig()
        assert cfg.api_key == "test-key-12345678"
        assert cfg.temperature == 0.5
        assert cfg.dry_run is True

    def test_invalid_float_falls_back(self, monkeypatch):
        monkeypatch.setenv("TEMPERATURE", "not-a-number")
        cfg = GlobalConfig()
        assert cfg.temperature == 0.9  # default

    def test_invalid_int_falls_back(self, monkeypatch):
        monkeypatch.setenv("MAX_TOKENS", "abc")
        cfg = GlobalConfig()
        assert cfg.max_tokens == 4096

    def test_masked_hides_api_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "abcdefghijklmnop")
        cfg = GlobalConfig()
        masked = cfg.masked()
        # 应显示前 4 + *** + 后 3
        assert masked["api_key"].startswith("abcd")
        assert "***" in masked["api_key"]
        assert masked["api_key"].endswith("nop")

    def test_masked_empty_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = GlobalConfig()
        masked = cfg.masked()
        assert masked["api_key"] == ""


class TestEnvHelpers:
    def test_env_bool_truthy(self, monkeypatch):
        for v in ("1", "true", "yes", "on"):
            monkeypatch.setenv("X", v)
            assert _env_bool("X", False) is True

    def test_env_bool_falsy(self, monkeypatch):
        for v in ("0", "false", "no", "off"):
            monkeypatch.setenv("X", v)
            assert _env_bool("X", True) is False

    def test_env_bool_invalid_returns_default(self, monkeypatch):
        monkeypatch.setenv("X", "garbage")
        assert _env_bool("X", True) is True
        assert _env_bool("X", False) is False

    def test_env_float_invalid(self, monkeypatch):
        monkeypatch.setenv("X", "abc")
        assert _env_float("X", 1.5) == 1.5

    def test_env_int_invalid(self, monkeypatch):
        monkeypatch.setenv("X", "abc")
        assert _env_int("X", 42) == 42


class TestFindProjectRoot:
    def test_finds_in_current(self, tmp_path):
        (tmp_path / ".novel").mkdir()
        assert find_project_root(tmp_path) == tmp_path

    def test_finds_in_parent(self, tmp_path):
        (tmp_path / ".novel").mkdir()
        sub = tmp_path / "sub" / "deeper"
        sub.mkdir(parents=True)
        assert find_project_root(sub) == tmp_path

    def test_returns_none_if_not_found(self, tmp_path):
        assert find_project_root(tmp_path) is None