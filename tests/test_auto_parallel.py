"""novel.auto 并发章节生成测试：DRY_RUN 模式覆盖 _writing_phase_parallel。

关注点：
  1. parallel >= 2 触发并发路径（_writing_phase_parallel）
  2. 并发不丢章节：state.chapters_done 仍 == chapters_total
  3. state.json 不被破坏（写竞争靠 state_lock 解决）
  4. book.md 完整产出
  5. 并发快于串行（DRY_RUN 下应至少不慢于串行；这里不强测 wall-clock，避免 flaky）
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from novel.auto import (
    _writing_phase,
    _writing_phase_parallel,
)
from novel.auto_state import AutoState, Phase, QualityPreset
from novel.storage import init_project
from novel_cli import app


runner = CliRunner()


@pytest.fixture
def dry_run_env(monkeypatch):
    """DRY_RUN 模式 + 测试 API key。"""
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")
    yield


@pytest.fixture
def dry_run_global(monkeypatch):
    """让 load_global() 返回 dry_run=True。"""
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345678")


class TestParallelDispatch:
    """parallel 字段在 AutoSpec 里的语义。"""

    def test_default_parallel_is_zero(self):
        from novel.auto_state import AutoSpec
        spec = AutoSpec(title="t", target_words=9000, target_chapters=3)
        assert spec.parallel == 0
        assert isinstance(spec.parallel, int)

    def test_parallel_setter_to_int(self):
        from novel.auto_state import AutoSpec
        spec = AutoSpec(title="t", target_words=9000, target_chapters=3, parallel=4)
        assert spec.parallel == 4

    def test_negative_parallel_clamped(self):
        from novel.auto_state import AutoSpec
        spec = AutoSpec(title="t", target_words=9000, target_chapters=3, parallel=-1)
        # __post_init__ 把负数当无效
        assert spec.parallel >= 0


class TestParallelEndToEnd:
    """DRY_RUN 完整跑 6 章，并发为 4：state 完整 + book.md 存在。"""

    def test_parallel_4_writes_all_chapters(self, tmp_path, dry_run_env):
        from novel.auto import run_auto_novel
        from novel.auto_state import AutoSpec

        spec = AutoSpec(
            title="parallel_test",
            target_words=18000,
            target_chapters=6,
            quality=QualityPreset.DRAFT,
            parallel=4,
        )
        out = run_auto_novel(spec, tmp_path)
        assert out.exists()
        assert out.name == "book.md"

        # state 完整
        state = AutoState.load(tmp_path)
        assert state is not None
        assert state.phase == Phase.DONE
        assert state.chapters_total == 6
        assert len(state.chapters_done) == 6
        # 并发路径写入：state.chapter_results 应该有全部 6 章
        assert len(state.chapter_results) == 6

    def test_parallel_8_high_concurrency(self, tmp_path, dry_run_env):
        from novel.auto import run_auto_novel
        from novel.auto_state import AutoSpec

        spec = AutoSpec(
            title="hi_conc",
            target_words=30000,
            target_chapters=10,
            quality=QualityPreset.DRAFT,
            parallel=8,  # > chapters 也安全
        )
        out = run_auto_novel(spec, tmp_path)
        assert out.exists()
        state = AutoState.load(tmp_path)
        assert state.phase == Phase.DONE
        assert len(state.chapters_done) == 10

    def test_parallel_1_falls_back_to_serial(self, tmp_path, dry_run_env):
        """parallel=1 应走串行分支（_writing_phase），行为不变。"""
        from novel.auto import run_auto_novel
        from novel.auto_state import AutoSpec

        spec = AutoSpec(
            title="serial_fallback",
            target_words=6000,
            target_chapters=2,
            quality=QualityPreset.DRAFT,
            parallel=1,  # 等价于 0/串行
        )
        out = run_auto_novel(spec, tmp_path)
        assert out.exists()
        state = AutoState.load(tmp_path)
        assert state.chapters_total == 2
        assert len(state.chapters_done) == 2


class TestParallelCLI:
    """novel_cli --parallel 参数透传到 AutoSpec。"""

    def test_auto_with_parallel_4(self, tmp_path, monkeypatch, dry_run_env):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [
            "auto", "demo",
            "--title", "并行测试",
            "--theme", "DRY_RUN 并发",
            "--words", "6000",
            "--chapters", "3",
            "--quality", "draft",
            "--parallel", "4",
        ])
        assert result.exit_code == 0, result.stdout
        # 项目应建出来 + state 到 DONE
        project = tmp_path / "demo"
        assert (project / ".novel" / "auto_state.json").exists()
        state = AutoState.load(project)
        assert state is not None
        assert len(state.chapters_done) == 3

    def test_write_help_shows_parallel_flag(self):
        result = runner.invoke(app, ["write", "--help"])
        assert result.exit_code == 0
        assert "--parallel" in result.stdout

    def test_webnovel_pack_help_shows_parallel_flag(self):
        result = runner.invoke(app, ["webnovel-pack", "--help"])
        assert result.exit_code == 0
        assert "--parallel" in result.stdout


class TestParallelStateSafety:
    """并发场景下 state.json 文件不会被破坏（不丢字符、不格式错乱）。"""

    def test_state_file_valid_json_after_parallel(self, tmp_path, dry_run_env):
        import json

        from novel.auto import run_auto_novel
        from novel.auto_state import AutoSpec

        spec = AutoSpec(
            title="state_safety",
            target_words=12000,
            target_chapters=4,
            quality=QualityPreset.DRAFT,
            parallel=4,
        )
        run_auto_novel(spec, tmp_path)
        # 读盘 JSON 应能 parse（state_lock 保证原子写）
        state_path = tmp_path / ".novel" / "auto_state.json"
        assert state_path.exists()
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert "phase" in data
        assert "chapters_done" in data
        # DONE 阶段
        assert data["phase"] == "done"

    def test_no_state_corruption_under_concurrent_writes(self, tmp_path, dry_run_env):
        """模拟并发场景：state.cumulative_tokens 应是连贯累加。"""
        from novel.auto import run_auto_novel
        from novel.auto_state import AutoSpec

        spec = AutoSpec(
            title="concurrent_tokens",
            target_words=9000,
            target_chapters=5,
            quality=QualityPreset.DRAFT,
            parallel=3,
        )
        run_auto_novel(spec, tmp_path)
        state = AutoState.load(tmp_path)
        # cumulative_tokens 应 >= 0（不会因 race 变负数）
        assert state.cumulative_tokens >= 0
        # 5 章都应有 chapter_results
        for n in range(1, 6):
            assert n in state.chapter_results
            assert state.chapter_results[n].chapter_no == n
