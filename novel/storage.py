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
    def world_path(self):
        return self.novel_dir / "world.md"

    @property
    def timeline_path(self):
        return self.novel_dir / "timeline.md"

    @property
    def state_path(self):
        return self.novel_dir / "state.md"

    @property
    def rolling_summary_path(self):
        return self.novel_dir / "rolling_summary.md"

    @property
    def volumes_path(self):
        return self.novel_dir / "volumes.md"

    @property
    def arcs_dir(self):
        return self.novel_dir / "arcs"

    @property
    def samples_dir(self):
        return self.novel_dir / "samples"

    @property
    def foreshadowing_path(self):
        return self.novel_dir / "foreshadowing.md"

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
    (root / PROJECT_DIR / "arcs").mkdir()
    (root / PROJECT_DIR / "reports").mkdir()
    (root / PROJECT_DIR / "samples").mkdir(exist_ok=True)
    p = Project(root=root, title=title, meta=meta or {"theme": theme})
    _write_yaml(p.project_yaml, {"title": title, "theme": theme, **(meta or {})})
    if theme and not p.outline_path.exists():
        p.outline_path.write_text(
            "# 大纲\n\n> 主题: " + theme + "\n\n（待生成）\n",
            encoding="utf-8",
        )
    if not p.state_path.exists():
        p.state_path.write_text("# 故事状态\n\n（暂无；写完第一章后会自动生成摘要）\n", encoding="utf-8")
    if not p.rolling_summary_path.exists():
        p.rolling_summary_path.write_text("# 滚动摘要\n\n（暂无；每写完 5 章自动更新一次）\n", encoding="utf-8")
    if not p.world_path.exists():
        p.world_path.write_text("# 世界观\n\n（待生成；包括地理、历史、关键设定、神话、地理与时代的硬规则）\n", encoding="utf-8")
    if not p.timeline_path.exists():
        p.timeline_path.write_text("# 时间线\n\n（待生成；按故事内时间顺序记录关键事件）\n", encoding="utf-8")
    if not p.foreshadowing_path.exists():
        p.foreshadowing_path.write_text("# 伏笔簿\n\n（待生成；记录埋下的钩子与回收时间）\n", encoding="utf-8")
    if not p.volumes_path.exists():
        p.volumes_path.write_text("# 分卷\n\n（待生成；长篇可分多卷，每卷一个核心冲突）\n", encoding="utf-8")
    return p


def load_project(root=None):
    """从当前目录加载小说项目。

    找不到 .novel 时抛出友好的 ProjectNotFoundError，
    提示用户用 novel init 初始化或在已有项目目录里执行命令。
    """
    from .config import find_project_root

    base = (root or Path.cwd()).resolve()
    proj_root = find_project_root(base)
    if not proj_root:
        raise ProjectNotFoundError(
            "未找到 .novel 项目目录。\n"
            "  当前目录: " + str(base) + "\n"
            "  解决方法：\n"
            "    - 如果还没建项目：cd 到想写小说的位置，执行 `novel init <name>`\n"
            "    - 如果已建项目：cd 进入项目根目录（包含 .novel 的那层）\n"
            "    - 想要强制在当前目录建项目：`novel init . --here`"
        )
    yml = proj_root / PROJECT_DIR / "project.yaml"
    if not yml.exists():
        raise ProjectNotFoundError(
            "项目元信息缺失：" + str(yml) + "\n"
            "项目目录可能损坏。运行 `novel doctor` 诊断，或删除 .novel 重做。"
        )
    data = _read_yaml(yml) or {}
    return Project(root=proj_root, title=data.get("title", proj_root.name), meta=data)


class ProjectNotFoundError(FileNotFoundError):
    """未找到项目目录。用 FileNotFoundError 兼容旧的 except，但携带更友好的 message。"""

    def __str__(self):
        return self.args[0] if self.args else "project not found"


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

def load_titles(project):
    import json
    p = project.novel_dir / "titles.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_titles(project, titles):
    import json
    p = project.novel_dir / "titles.json"
    p.write_text(json.dumps(titles, ensure_ascii=False, indent=2), encoding="utf-8")

def get_existing_titles(project):
    titles = load_titles(project)
    if not titles:
        return ""
    items = []
    for k in sorted(titles.keys()):
        items.append(k + ": " + titles[k])
    return "\n".join(items)


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
