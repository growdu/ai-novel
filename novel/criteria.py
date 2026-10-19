"""v0.15 daemon 用：解析用户的 quality_criteria.md + LLM 评估器。

文件格式（plain markdown，每行一条硬指标）：

    # 硬指标（可选标题）
    - 第三章不能出现内心独白
    - 全书 AI 味指数均值 < 40
    - 主要人物姓名一致
    - 每章 ≥ 2500 字

`load_criteria(path)` 解析 → list[str]（每条去掉 `- ` 前缀和首尾空格）

`evaluate_via_llm(criteria_lines, full_text, prev_feedback, client)` 调 LLM
按 prompts/daemon_criteria.md 评估，返回 EvaluatorReport。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from novel.llm import LLMClient
from novel.config import GlobalConfig
from novel.prompts import build_daemon_criteria_messages


__all__ = [
    "load_criteria",
    "evaluate_via_llm",
    "format_feedback_for_next_iter",
    "CriterionResult",
    "EvaluatorReport",
    "LLMClient",
]


@dataclass
class CriterionResult:
    """单条硬指标的评估结果。"""
    id: int
    text: str
    passed: bool
    evidence: str = ""
    suggestion: str = ""


@dataclass
class EvaluatorReport:
    """LLM 评估器一次调用的整体结果。"""
    summary: str
    all_passed: bool
    criteria: list[CriterionResult] = field(default_factory=list)
    top_priority_fixes: list[str] = field(default_factory=list)
    failed_chapters: list[int] = field(default_factory=list)  # v0.16+ surgical rebuild
    raw_text: str = ""   # 原始 LLM 输出（debug 用）

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "all_passed": self.all_passed,
            "criteria": [
                {"id": c.id, "text": c.text, "passed": c.passed,
                 "evidence": c.evidence, "suggestion": c.suggestion}
                for c in self.criteria
            ],
            "top_priority_fixes": list(self.top_priority_fixes),
            "failed_chapters": list(self.failed_chapters),
        }


def load_criteria(path: str | Path) -> list[str]:
    """解析用户 quality_criteria.md，每行一条硬指标。

    跳过：空行 / 纯标题行（# 开头） / 代码块（``` 包裹）

    Returns:
        list[str]: 每条去掉 `- ` 前缀和首尾空格。
    """
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    in_code_block = False
    for line in lines:
        s = line.rstrip()
        if s.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        s = s.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        # 列表项：- text / * text / 数字. text
        m = re.match(r"^[-*]\s+(.*)$", s)
        if m:
            out.append(m.group(1).strip())
            continue
        m = re.match(r"^\d+\.\s+(.*)$", s)
        if m:
            out.append(m.group(1).strip())
            continue
        # 纯文本行也算一条（用户可能没加列表符号）
        out.append(s)
    return out


def _extract_json_block(text: str) -> str:
    """从 LLM 输出里抠出 JSON 代码块（```json ... ``` 包裹）。

    找不到任何 JSON 标记时返回空字符串（让上层走「JSON parse failed」路径）。
    """
    if not text:
        return ""
    # 优先匹配 ```json ... ```
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    # 兜底：找第一个 { 到最后一个 } 的整段
    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start : end + 1]
    return ""


def _parse_report(parsed: dict) -> EvaluatorReport:
    """把 LLM JSON 输出解析成 EvaluatorReport。容错处理：字段缺失用空。"""
    summary = str(parsed.get("summary", ""))
    all_passed = bool(parsed.get("all_passed", False))
    criteria = []
    for c in parsed.get("criteria", []) or []:
        try:
            cid = int(c.get("id", len(criteria) + 1))
        except (TypeError, ValueError):
            cid = len(criteria) + 1
        criteria.append(CriterionResult(
            id=cid,
            text=str(c.get("text", "")),
            passed=bool(c.get("passed", False)),
            evidence=str(c.get("evidence", "")),
            suggestion=str(c.get("suggestion", "")),
        ))
    fixes = parsed.get("top_priority_fixes", []) or []
    if isinstance(fixes, str):
        fixes = [fixes]
    # v0.16+：failed_chapters 解析（LLM 输出如 [3, 7, 12]）
    raw_failed = parsed.get("failed_chapters", []) or []
    failed_chapters: list[int] = []
    if isinstance(raw_failed, list):
        for x in raw_failed:
            try:
                failed_chapters.append(int(x))
            except (TypeError, ValueError):
                continue
    failed_chapters = sorted(set(failed_chapters))
    return EvaluatorReport(
        summary=summary,
        all_passed=all_passed,
        criteria=criteria,
        top_priority_fixes=[str(f) for f in fixes],
        failed_chapters=failed_chapters,
    )


def evaluate_via_llm(
    criteria_lines: list[str],
    full_text: str,
    prev_feedback: str = "",
    client=None,
    target_words: int = 800,
) -> EvaluatorReport:
    """调 LLM 评估小说是否满足 criteria。

    Args:
        criteria_lines: load_criteria() 解析出的指标列表
        full_text: 完整小说正文（所有章节合并）
        prev_feedback: 上一轮评估的 top_priority_fixes（注入到 prompt）
        client: LLMClient 实例（None 用默认）
        target_words: LLM 输出的 target words（评估报告不长）

    Returns:
        EvaluatorReport: 解析后的报告；JSON 解析失败时返回空 + all_passed=False
    """
    if not criteria_lines:
        return EvaluatorReport(summary="无 criteria", all_passed=True)

    client = client or LLMClient(GlobalConfig())
    msgs = build_daemon_criteria_messages(criteria_lines, full_text, prev_feedback)
    res = client.chat_with_continuation(
        msgs, target_words=target_words, max_total_tokens=16000, temperature=0.3,
    )
    raw = (res.content or "").strip()
    json_text = _extract_json_block(raw)
    if not json_text:
        return EvaluatorReport(
            summary="LLM 输出无可解析 JSON",
            all_passed=False,
            raw_text=raw,
        )
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError:
        return EvaluatorReport(
            summary=f"JSON parse failed: {raw[:200]}",
            all_passed=False,
            raw_text=raw,
        )
    report = _parse_report(parsed)
    report.raw_text = raw
    return report


def format_feedback_for_next_iter(report: EvaluatorReport) -> str:
    """把 EvaluatorReport 转换成「下一轮 prompt 注入」用的紧凑文本。"""
    if report.all_passed:
        return ""
    parts = [f"上轮评估未通过。{report.summary}"]
    for c in report.criteria:
        if not c.passed:
            parts.append(f"- [{c.id}] {c.text} → 证据：{c.evidence} → 建议：{c.suggestion}")
    if report.top_priority_fixes:
        parts.append("\n优先修复：")
        for fix in report.top_priority_fixes[:3]:
            parts.append(f"  * {fix}")
    return "\n".join(parts)
