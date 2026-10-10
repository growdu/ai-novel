"""项目存储：把小说项目存到本地 .novel/ 目录。"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_DIR = ".novel"


@dataclass
class Project:
    root: Path
    title: str
    meta: dict = field(default_factory=dict)

    @property
    def novel_dir(self):
        return self.root / PROJECT_DIR

    @property
    def outline_path(self):
        return self.novel_dir / "outline.md"

    @property
    def characters_path(self):
        return self.novel_dir / "characters.md"

    @property
    def style_path(self):
        return self.novel_dir / "style.md"

    @property
    def chapters_dir(self):
        return self.novel_dir / "chapters"

    @property
    def history_dir(self):
        return self.novel_dir / "history"

    @property
    def project_yaml(self):
        return self.novel_dir / "project.yaml"

    def list_chapters(self):
        if not self.chapters_dir.exists():
            return []
        return sorted(self.chapters_dir.glob("[0-9]*.md"))


def init_project(root, title, theme="", meta=None):
    root = root.resolve()
    if (root / PROJECT_DIR).exists():
        raise FileExistsError("项目目录已存在: " + str(root / PROJECT_DIR))
    (root / PROJECT_DIR).mkdir(parents=True)
    (root / PROJECT_DIR / "chapters").mkdir()
    (root / PROJECT_DIR / "history").mkdir()
    p = Project(root=root, title=title, meta=meta or {"theme": theme})
    _write_yaml(p.project_yaml, {"title": title, "theme": theme, **(meta or {})})
    if theme and not p.outline_path.exists():
        p.outline_path.write_text(
            "# 大纲\n\n> 主题: " + theme + "\n\n（待生成）\n",
            encoding="utf-8",
        )
    return p


def load_project(root=None):
    from .config import find_project_root

    base = (root or Path.cwd()).resolve()
    proj_root = find_project_root(base)
    if not proj_root:
        raise FileNotFoundError("未找到 .novel 项目目录，请先在小说根目录运行 novel init 初始化。")
    yml = proj_root / PROJECT_DIR / "project.yaml"
    if not yml.exists():
        raise FileNotFoundError("项目元信息缺失: " + str(yml))
    data = _read_yaml(yml) or {}
    return Project(root=proj_root, title=data.get("title", proj_root.name), meta=data)


def save_chapter(project, chapter_no, content, backup=True):
    target = project.chapters_dir / ("%04d.md" % chapter_no)
    if target.exists() and backup:
        hist_dir = project.history_dir
        hist_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(hist_dir.glob("chapter_%04d_v*.md" % chapter_no))
        nxt = len(existing) + 1
        shutil.copy2(target, hist_dir / ("chapter_%04d_v%d.md" % (chapter_no, nxt)))
    target.write_text(content, encoding="utf-8")
    return target


def load_chapter(project, chapter_no):
    p = project.chapters_dir / ("%04d.md" % chapter_no)
    return p.read_text(encoding="utf-8") if p.exists() else None


def chapter_word_count(text):
    """粗略字数：中文按字数、英文按词数。"""
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^\)]*\)", r"\1", text)
    text = re.sub(r"[#>*_~\-]", "", text)
    cn = len(re.findall(r"[\u4e00-\u9fff]", text))
    en = len(re.findall(r"[A-Za-z]+", text))
    return cn + en


def _write_yaml(path, data):
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _read_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
