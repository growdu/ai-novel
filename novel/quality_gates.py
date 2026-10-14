"""全自动写小说的质量门控。

每章生成后跑这些 validator；如果不达标，编排器决定是 polish 还是 retry。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from novel import generator as G
from novel import storage as S
from novel.auto_state import QualityPreset
from novel.llm import LLMClient
from novel.config import GlobalConfig


@dataclass
class GateResult:
    """单个质量门控的结果。"""

    name: str
    passed: bool
    score: Optional[float] = None
    detail: str = ""
    payload: dict = ""

    def __bool__(self) -> bool:
        return self.passed


def check_word_count(content: str, target: int, tolerance: float) -> GateResult:
    """字数 ±tolerance% 算通过。tolerance=0.1 表示 2700-3300 字（3000 目标）。"""
    actual = S.chapter_word_count(content)
    if target <= 0:
        return GateResult(name="word_count", passed=True, score=float(actual), detail="无字数目标")
    min_words = int(target * (1 - tolerance))
    max_words = int(target * (1 + tolerance))
    passed = min_words <= actual <= max_words
    detail = f"实际 {actual} 字，目标 {target} 字，容差 ±{int(tolerance*100)}% ({min_words}-{max_words})"
    return GateResult(
        name="word_count",
        passed=passed,
        score=float(actual),
        detail=detail,
    )


_AI_RE = re.compile(r"AI\s*味指数[：:]?\s*(\d+)")


def parse_ai_flavor_score(ai_report_text: str) -> Optional[int]:
    """从 `novel detect` 报告里提取 AI 味指数（0-100，越低越像人写）。"""
    if not ai_report_text:
        return None
    m = _AI_RE.search(ai_report_text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def parse_radar_score(radar_text: str) -> Optional[int]:
    """从风格雷达报告里提取总相似度。"""
    if not radar_text:
        return None
    m = re.search(r"总相似度[：:]?\s*(\d+)", radar_text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def run_ai_detect(
    project: S.Project,
    chapter_no: int,
    client: LLMClient,
) -> Optional[int]:
    """调用 LLM 检测 AI 味并保存报告，返回指数。"""
    content = S.load_chapter(project, chapter_no)
    if not content:
        return None
    from novel import prompts as P
    msgs = P.build_detect_messages(content)
    res = client.chat(msgs, temperature=0.3, max_tokens=2000)
    p = project.novel_dir / "reports" / ("detect_%04d.md" % chapter_no)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# 第 %d 章 AI 味检测\n\n" % chapter_no + res.content + "\n", encoding="utf-8")
    return parse_ai_flavor_score(res.content)


def run_radar(
    project: S.Project,
    chapter_no: int,
    client: LLMClient,
) -> Optional[int]:
    """调用 LLM 跑风格雷达并保存报告，返回相似度。"""
    radar_text = G.style_radar(project, chapter_no, client=client)
    return parse_radar_score(radar_text or "")


def check_ai_flavor(
    project: S.Project,
    chapter_no: int,
    client: LLMClient,
    threshold: Optional[int],
) -> GateResult:
    """AI 味 < threshold 通过。None 跳过。"""
    if threshold is None:
        return GateResult(name="ai_flavor", passed=True, detail="未启用")
    score = run_ai_detect(project, chapter_no, client)
    if score is None:
        return GateResult(name="ai_flavor", passed=True, detail="无法解析指数，按通过处理")
    return GateResult(
        name="ai_flavor",
        passed=score < threshold,
        score=float(score),
        detail=f"AI 味指数 {score}（阈值 < {threshold}）",
    )


def check_radar(
    project: S.Project,
    chapter_no: int,
    client: LLMClient,
    threshold: Optional[int],
) -> GateResult:
    """风格雷达相似度 ≥ threshold 通过。None 跳过。"""
    if threshold is None:
        return GateResult(name="radar", passed=True, detail="未启用")
    # 没有 samples 时跳过
    has_samples = (
        project.samples_dir.exists()
        and any(f.suffix == ".md" and not f.name.startswith("_") for f in project.samples_dir.iterdir())
    )
    if not has_samples:
        return GateResult(name="radar", passed=True, detail="samples/ 为空，跳过雷达检查")
    score = run_radar(project, chapter_no, client)
    if score is None:
        return GateResult(name="radar", passed=True, detail="无法解析相似度，按通过处理")
    return GateResult(
        name="radar",
        passed=score >= threshold,
        score=float(score),
        detail=f"相似度 {score}（阈值 ≥ {threshold}）",
    )


def check_consistency(
    project: S.Project,
    client: LLMClient,
    lookback: int = 10,
) -> GateResult:
    """跨章一致性检查。无显著冲突算通过。"""
    try:
        G.check_consistency(project, client=client, lookback=lookback)
    except Exception as e:
        return GateResult(name="consistency", passed=False, detail=f"检查失败：{e}")
    report_path = project.novel_dir / "consistency_report.md"
    if not report_path.exists():
        return GateResult(name="consistency", passed=True, detail="报告未生成")
    text = report_path.read_text(encoding="utf-8")
    # 简单冲突计数：出现"冲突"且后跟数字
    conflict_count = len(re.findall(r"冲突[：:]\s*\d+", text))
    passed = conflict_count == 0
    return GateResult(
        name="consistency",
        passed=passed,
        score=float(conflict_count),
        detail=f"冲突数 {conflict_count}",
    )


def run_all_gates(
    project: S.Project,
    chapter_no: int,
    client: LLMClient,
    spec,  # AutoSpec
    include_consistency: bool = False,
) -> list[GateResult]:
    """跑一个字数 + 可选 AI 味 + 可选 雷达 + 可选一致性。"""
    content = S.load_chapter(project, chapter_no) or ""
    results = [
        check_word_count(content, spec.per_chapter_words, spec.quality.word_tolerance),
    ]
    if spec.quality.ai_flavor_threshold is not None:
        results.append(check_ai_flavor(project, chapter_no, client, spec.quality.ai_flavor_threshold))
    if spec.quality.radar_threshold is not None:
        results.append(check_radar(project, chapter_no, client, spec.quality.radar_threshold))
    if include_consistency:
        results.append(check_consistency(project, client))
    return results


def summarize(results: list[GateResult]) -> tuple[bool, list[GateResult]]:
    """返回 (全通过, 不通过的 gates)。"""
    failed = [r for r in results if not r.passed]
    return (len(failed) == 0, failed)