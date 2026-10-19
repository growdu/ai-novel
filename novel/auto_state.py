"""一键全自动写小说的状态机。

设计目标：跑几十章长篇任务时支持中断恢复 + 进度可视化。
AutoState 是 dataclass，写盘/读盘走 .novel/auto_state.json。

状态机阶段：
  PLANNING       - outline / characters / world / volumes / chapter_plans
  WRITING        - 逐章生成
  POLISHING      - 批量润色
  CONSISTENCY    - 跨章一致性检查 + 修复
  EXPORTING      - book.md 合并导出
  DONE           - 全部成功
  FAILED         - 致命错误（用户需手动处理）
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class Phase(str, Enum):
    """全自动写小说的阶段。"""

    PLANNING = "planning"
    WRITING = "writing"
    POLISHING = "polishing"
    CONSISTENCY = "consistency"
    EXPORTING = "exporting"
    DONE = "done"
    FAILED = "failed"

    @property
    def is_done(self) -> bool:
        return self in (Phase.DONE, Phase.FAILED)


class QualityPreset(str, Enum):
    """质量档位。"""

    DRAFT = "draft"          # 速度优先，1 轮，无自动 polish
    STANDARD = "standard"    # 平衡，2 轮，字数 ±20%
    PREMIUM = "premium"      # 精修，3 轮，字数 ±10%，AI 味 < 30

    @property
    def iters(self) -> int:
        return {"draft": 1, "standard": 2, "premium": 3}[self.value]

    @property
    def word_tolerance(self) -> float:
        return {"draft": 0.3, "standard": 0.2, "premium": 0.1}[self.value]

    @property
    def ai_flavor_threshold(self) -> Optional[int]:
        # None 表示不检查；数字是允许的最大 AI 味指数
        return {"draft": None, "standard": 50, "premium": 30}[self.value]

    @property
    def radar_threshold(self) -> Optional[int]:
        return {"draft": None, "standard": 60, "premium": 70}[self.value]

    @property
    def max_retries(self) -> int:
        return {"draft": 1, "standard": 2, "premium": 3}[self.value]


@dataclass
class AutoSpec:
    """用户输入的全自动写小说规格。"""

    title: str
    theme: str = ""
    genre: str = "现实 / 严肃文学"
    style: str = ""
    target_words: int = 200000
    target_chapters: int = 0           # 0 = 自动 = target_words // 3000
    quality: QualityPreset = QualityPreset.PREMIUM
    budget_cny: float = 0.0            # 0 = 不限
    parallel: int = 0                  # 并发 worker 数：0/1=串行，>=2=并发（v0.13）
    samples_dir: Optional[str] = None  # 自定义风格样本路径
    wait_on_quota: bool = True          # 撞配额时自动等到重置（v0.14）
    max_wait_seconds: int = 21600      # 撞配额单次最多等 6 小时（v0.14）
    daemon_criteria_path: str = ""       # 用户硬指标文件路径（v0.15 daemon）
    max_iterations: int = 3             # daemon 最多迭代轮数（v0.15）
    max_time_seconds: int = 0           # daemon 总时间上限 0=无限（v0.15）
    extra: str = ""                     # 注入到 prompts 的额外文本（v0.15 daemon 用反馈）

    def __post_init__(self):
        if self.target_chapters <= 0:
            # 每章默认 3000 字
            self.target_chapters = max(1, self.target_words // 3000)
        # 自动算每章目标字数
        self.per_chapter_words = max(2000, self.target_words // self.target_chapters)
        # 兼容历史 bool 入参
        if self.parallel < 0:
            self.parallel = 0
        if self.max_wait_seconds < 0:
            self.max_wait_seconds = 0  # 0 = 不等，立即退出（用 --no-wait 替代）


@dataclass
class ChapterResult:
    """单章生成结果记录。"""

    chapter_no: int
    status: str = "pending"   # pending / generated / polished / failed
    word_count: int = 0
    iterations: int = 0
    retries: int = 0
    ai_flavor: Optional[int] = None
    radar: Optional[int] = None
    elapsed_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_cny: float = 0.0
    error: str = ""


@dataclass
class AutoState:
    """持久化的全自动状态。每次关键步骤后写盘。"""

    spec: dict = field(default_factory=dict)
    phase: Phase = Phase.PLANNING
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    chapters_total: int = 0
    chapters_done: list[int] = field(default_factory=list)
    chapters_failed: list[int] = field(default_factory=list)
    chapter_results: dict[int, ChapterResult] = field(default_factory=dict)
    cumulative_tokens: int = 0
    cumulative_prompt_tokens: int = 0
    cumulative_completion_tokens: int = 0
    cumulative_cost_cny: float = 0.0
    budget_cny: float = 0.0
    last_error: str = ""
    planning_files: list[str] = field(default_factory=list)   # 已生成的 outline/characters/world/volumes
    polished: bool = False
    consistency_checked: bool = False
    exported_path: str = ""
    # v0.15+ daemon 字段
    iteration_count: int = 0                  # 跑了几轮（6 阶段 + criteria 检查）
    last_criteria_report: str = ""           # 最近一次 criteria 评估的原始 LLM 输出
    last_iter_passed: bool = False           # 最近一轮是否全 pass

    # ---- 序列化 ----
    def to_dict(self) -> dict:
        d = asdict(self)
        d["phase"] = self.phase.value
        d["chapter_results"] = {
            str(k): asdict(v) for k, v in self.chapter_results.items()
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AutoState":
        d = dict(d)
        d["phase"] = Phase(d["phase"])
        d["chapter_results"] = {
            int(k): ChapterResult(**v) for k, v in d.get("chapter_results", {}).items()
        }
        return cls(**d)

    def save(self, project_dir: Path) -> Path:
        """写到 .novel/auto_state.json（原子写）。"""
        from novel.storage import PROJECT_DIR

        state_path = project_dir / PROJECT_DIR / "auto_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = time.time()
        tmp = state_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, state_path)
        return state_path

    @classmethod
    def load(cls, project_dir: Path) -> Optional["AutoState"]:
        """从 .novel/auto_state.json 加载；不存在返回 None。"""
        from novel.storage import PROJECT_DIR

        state_path = project_dir / PROJECT_DIR / "auto_state.json"
        if not state_path.exists():
            return None
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # 损坏的状态——返回 None 让用户重新跑
            return None

    @classmethod
    def clear(cls, project_dir: Path) -> None:
        from novel.storage import PROJECT_DIR

        state_path = project_dir / PROJECT_DIR / "auto_state.json"
        if state_path.exists():
            state_path.unlink()

    # ---- 进度查询 ----
    @property
    def progress_ratio(self) -> float:
        if self.chapters_total <= 0:
            return 0.0
        done = len(self.chapters_done)
        return min(1.0, done / self.chapters_total)

    @property
    def total_words(self) -> int:
        return sum(r.word_count for r in self.chapter_results.values())

    def is_chapter_done(self, n: int) -> bool:
        return n in self.chapters_done

    def mark_chapter_done(self, result: ChapterResult) -> None:
        self.chapter_results[result.chapter_no] = result
        if result.chapter_no not in self.chapters_done:
            self.chapters_done.append(result.chapter_no)
        if result.status == "failed":
            if result.chapter_no not in self.chapters_failed:
                self.chapters_failed.append(result.chapter_no)

    def estimate_remaining_chapters(self) -> int:
        return max(0, self.chapters_total - len(self.chapters_done))

    def estimate_total_cost(self, avg_cost_per_chapter: float) -> float:
        return avg_cost_per_chapter * self.chapters_total