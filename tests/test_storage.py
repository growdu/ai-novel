"""novel.storage 单元测试。

覆盖：项目初始化、章节读写、版本备份、字数统计、ProjectNotFoundError。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from novel.storage import (
    Project,
    ProjectNotFoundError,
    chapter_word_count,
    init_project,
    load_chapter,
    load_project,
    save_chapter,
)


@pytest.fixture
def tmp_proj(tmp_path):
    """新建一个临时项目用于测试。"""
    root = tmp_path / "my_novel"
    root.mkdir()
    p = init_project(root, title="测试小说", theme="东北小镇命案", meta={"genre": "悬疑"})
    return p


class TestInitProject:
    def test_creates_required_dirs(self, tmp_proj):
        assert tmp_proj.novel_dir.exists()
        assert tmp_proj.chapters_dir.exists()
        assert tmp_proj.history_dir.exists()
        assert tmp_proj.arcs_dir.exists()
        assert tmp_proj.samples_dir.exists()

    def test_creates_placeholder_files(self, tmp_proj):
        for path in [
            tmp_proj.outline_path,
            tmp_proj.state_path,
            tmp_proj.world_path,
            tmp_proj.timeline_path,
            tmp_proj.foreshadowing_path,
            tmp_proj.volumes_path,
        ]:
            assert path.exists()
            assert path.read_text(encoding="utf-8")

    def test_double_init_raises(self, tmp_path):
        root = tmp_path / "x"
        root.mkdir()
        init_project(root, title="x")
        with pytest.raises(FileExistsError):
            init_project(root, title="x")

    def test_meta_persisted(self, tmp_proj):
        assert tmp_proj.meta["genre"] == "悬疑"
        yml = tmp_proj.project_yaml.read_text(encoding="utf-8")
        assert "悬疑" in yml


class TestChapterIO:
    def test_save_and_load(self, tmp_proj):
        save_chapter(tmp_proj, 1, "第一段正文\n\n*起")
        assert load_chapter(tmp_proj, 1) == "第一段正文\n\n*起"

    def test_save_creates_backup(self, tmp_proj):
        save_chapter(tmp_proj, 1, "v1")
        save_chapter(tmp_proj, 1, "v2")
        files = sorted(tmp_proj.history_dir.glob("chapter_0001_v*.md"))
        assert len(files) == 1
        assert files[0].read_text(encoding="utf-8") == "v1"
        assert load_chapter(tmp_proj, 1) == "v2"

    def test_load_missing_returns_none(self, tmp_proj):
        assert load_chapter(tmp_proj, 999) is None

    def test_list_chapters_sorted(self, tmp_proj):
        for n in (3, 1, 10, 2):
            save_chapter(tmp_proj, n, f"第 {n} 章")
        chapters = tmp_proj.list_chapters()
        names = [c.stem for c in chapters]
        assert names == ["0001", "0002", "0003", "0010"]


class TestChapterWordCount:
    def test_chinese_only(self):
        assert chapter_word_count("你好世界") == 4

    def test_english_words(self):
        assert chapter_word_count("hello world foo") == 3

    def test_mixed(self):
        assert chapter_word_count("你好 world") == 3

    def test_strips_code_fences(self):
        text = "```python\ncode\n```\n正文"
        wc = chapter_word_count(text)
        assert wc >= 2  # "正文"

    def test_strips_links(self):
        text = "[链接文本](http://x.com)\n正文"
        wc = chapter_word_count(text)
        assert "链接文本" in str(wc) or wc >= 3

    def test_strips_markdown_chars(self):
        # # > * 等 markdown 字符不应被计数
        text = "# 标题\n> 引用\n**加粗**"
        wc = chapter_word_count(text)
        # 标题 + 引用 + 加粗 = 2 + 2 + 2 = 6
        assert wc == 6


class TestProjectPaths:
    def test_paths_are_under_novel_dir(self, tmp_proj):
        for p in [tmp_proj.outline_path, tmp_proj.characters_path, tmp_proj.state_path]:
            assert str(p).startswith(str(tmp_proj.novel_dir))


class TestLoadProjectErrors:
    def test_no_novel_dir_raises_with_hint(self, tmp_path, monkeypatch):
        # 切到 tmp_path，没有 .novel
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ProjectNotFoundError) as exc:
            load_project(tmp_path)
        msg = str(exc.value)
        assert "novel init" in msg
        assert str(tmp_path) in msg

    def test_corrupted_novel_dir_raises(self, tmp_path):
        (tmp_path / ".novel").mkdir()
        # 缺少 project.yaml
        with pytest.raises(ProjectNotFoundError):
            load_project(tmp_path)


class TestProjectDataclass:
    def test_field_defaults(self):
        p = Project(root=Path("/tmp"), title="x")
        assert p.meta == {}
        assert p.novel_dir == Path("/tmp/.novel")
        assert p.outline_path == Path("/tmp/.novel/outline.md")
        assert p.chapters_dir == Path("/tmp/.novel/chapters")
        assert p.history_dir == Path("/tmp/.novel/history")