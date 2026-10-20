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
from novel.prompts import (
    build_daemon_criteria_messages,
    build_daemon_criteria_batch_messages,
)


__all__ = [
    "load_criteria",
    "evaluate_via_llm",
    "evaluate_batches",
    "plan_batches",
    "plan_batches_by_chars",
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
    failed_chapters: list[int] = field(default_factory=list)  # v0.17 分块：这条指标在哪几章违反


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
                 "evidence": c.evidence, "suggestion": c.suggestion,
                 "failed_chapters": list(c.failed_chapters)}
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


def _coerce_int_list(raw) -> list[int]:
    """把 LLM 给的章节号列表转成升序去重的 int 列表。非 int 元素丢弃。"""
    out: list[int] = []
    if isinstance(raw, list):
        for x in raw:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                continue
    elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            out.append(int(raw))
        except (TypeError, ValueError):
            pass
    return sorted(set(out))


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
            # v0.17 分块：单条指标自己声明违反了哪几章
            failed_chapters=_coerce_int_list(c.get("failed_chapters", []) or []),
        ))
    fixes = parsed.get("top_priority_fixes", []) or []
    if isinstance(fixes, str):
        fixes = [fixes]
    # v0.16+：failed_chapters 解析（LLM 输出如 [3, 7, 12]）
    failed_chapters = _coerce_int_list(parsed.get("failed_chapters", []) or [])
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


# ---------------------------------------------------------------------------
# v0.17 分块评估：长篇项目（几百章）不能把整书塞进一个 prompt
# ---------------------------------------------------------------------------

DEFAULT_BATCH_SIZE = 12
DEFAULT_BATCH_OVERLAP = 4
MAX_BATCH_CHARS = 120_000  # 单批正文上限，防止 batch_size 大 + 章长时爆上下文


def plan_batches(n_items: int, batch_size: int = DEFAULT_BATCH_SIZE,
                 overlap: int = DEFAULT_BATCH_OVERLAP) -> list[tuple[int, int]]:
    """把 n_items 项切成若干 [(start, end)) 半开区间，尾部带重叠窗口。

    重叠是给「每 N 章至少一次」这类跨章窗口指标看的——只看批内证据也能判，
    但重叠能减少批次边界的盲区。

    Examples:
        >>> plan_batches(10, batch_size=4, overlap=1)
        [(0, 4), (3, 7), (6, 10)]
        >>> plan_batches(0)
        []
    """
    if n_items <= 0:
        return []
    batch_size = max(1, int(batch_size))
    overlap = max(0, min(int(overlap), batch_size - 1))
    step = batch_size - overlap
    out: list[tuple[int, int]] = []
    start = 0
    while start < n_items:
        end = min(start + batch_size, n_items)
        out.append((start, end))
        if end >= n_items:
            break
        start += step
    return out


def plan_batches_by_chars(chapters: list[dict], batch_size: int = DEFAULT_BATCH_SIZE,
                          overlap: int = DEFAULT_BATCH_OVERLAP,
                          max_chars: int = MAX_BATCH_CHARS) -> list[tuple[int, int]]:
    """按字符数二次收敛的切块：batch_size 和 max_chars 谁先到谁切。

    章节长短悬殊时（有的 500 字有的 8000 字）光按章数切仍可能爆上下文。
    """
    if not chapters:
        return []
    out: list[tuple[int, int]] = []
    start = 0
    n = len(chapters)
    while start < n:
        end = start
        chars = 0
        while end < n and (end - start) < max(1, batch_size):
            c = len(chapters[end].get("text", ""))
            if end > start and chars + c > max_chars:
                break
            chars += c
            end += 1
        out.append((start, end))
        if end >= n:
            break
        step = max(1, (end - start) - max(0, min(overlap, end - start - 1)))
        start += step
    return out


def _aggregate_batch_reports(reports: list[EvaluatorReport],
                             batch_ranges: list[tuple[int, int]],
                             criteria_lines: list[str]) -> EvaluatorReport:
    """把逐批报告聚合成一份全书报告。

    聚合语义：
      - criterion.passed = 该指标在**所有批**都通过才算通过（任一批挂即挂）
      - criterion.failed_chapters = 各批 failed_chapters 并集
      - evidence / suggestion 取**第一条失败**批次的（最有信息量）
      - 顶层 failed_chapters = 各批并集
      - 某指标在某批缺失 → 视为通过（不因模型漏报而误判失败）
    """
    agg: dict[int, CriterionResult] = {}
    failed_all: set[int] = set()
    fixes: list[str] = []
    seen_fixes: set[str] = set()
    ok_batches = 0

    for rep in reports:
        if rep.all_passed and not rep.failed_chapters and not any(
            not c.passed for c in rep.criteria
        ):
            ok_batches += 1
        failed_all |= set(rep.failed_chapters)
        for c in rep.criteria:
            cur = agg.get(c.id)
            if cur is None:
                cur = CriterionResult(
                    id=c.id,
                    text=c.text or (criteria_lines[c.id - 1]
                                    if 0 < c.id <= len(criteria_lines) else ""),
                    passed=c.passed,
                    evidence=c.evidence,
                    suggestion=c.suggestion,
                    failed_chapters=list(c.failed_chapters),
                )
                agg[c.id] = cur
            else:
                # 任一批失败 → 整体失败；保留首次失败的证据
                if not c.passed:
                    cur.passed = False
                    if not cur.evidence:
                        cur.evidence = c.evidence
                    if not cur.suggestion:
                        cur.suggestion = c.suggestion
                cur.failed_chapters = sorted(
                    set(cur.failed_chapters) | set(c.failed_chapters)
                )
        for f in rep.top_priority_fixes:
            fs = str(f).strip()
            if fs and fs not in seen_fixes:
                seen_fixes.add(fs)
                fixes.append(fs)

    # 兜底：模型完全没回的指标，按通过处理但保留 text
    for i, line in enumerate(criteria_lines, start=1):
        agg.setdefault(i, CriterionResult(id=i, text=line, passed=True))

    criteria_out = [agg[k] for k in sorted(agg)]
    # 未通过的指标排在前面，方便反馈注入取重点
    criteria_out.sort(key=lambda c: (c.passed, c.id))
    all_passed = not failed_all and all(c.passed for c in criteria_out)
    n_failed = len(failed_all)
    return EvaluatorReport(
        summary=(
            f"分块评估 {len(reports)} 批（{ok_batches} 批全通过）："
            f"{len(criteria_out) - sum(1 for c in criteria_out if c.passed)}"
            f"/{len(criteria_out)} 条指标未通过，涉及 {n_failed} 章"
        ),
        all_passed=all_passed,
        criteria=criteria_out,
        top_priority_fixes=fixes[:8],
        failed_chapters=sorted(failed_all),
        raw_text="",
    )


def evaluate_batches(
    criteria_lines: list[str],
    chapters: list[dict],
    batch_size: int = DEFAULT_BATCH_SIZE,
    overlap: int = DEFAULT_BATCH_OVERLAP,
    prev_feedback: str = "",
    client=None,
    target_words: int = 800,
    max_chars: int = MAX_BATCH_CHARS,
    on_progress=None,
) -> EvaluatorReport:
    """分块评估：把 chapters 切批，逐批调 LLM，最后聚合成一份报告。

    Args:
        criteria_lines: load_criteria() 的结果
        chapters: [{no, title, words, text}, ...]，需按章号升序
        batch_size: 每批最多几章
        overlap: 批间重叠章数（给「每 N 章」窗口指标留衔接）
        prev_feedback: 上一轮反馈，注入 prompt
        on_progress: 进度回调 on_progress(batch_idx, total, report_or_None)
            传 None 表示该批调用异常被跳过

    Returns:
        EvaluatorReport: 聚合报告。全空 chapters → all_passed=True。
    """
    if not criteria_lines:
        return EvaluatorReport(summary="无 criteria", all_passed=True)
    if not chapters:
        return EvaluatorReport(
            summary="无章节可评估", all_passed=False, failed_chapters=[]
        )

    client = client or LLMClient(GlobalConfig())
    ranges = plan_batches_by_chars(chapters, batch_size, overlap, max_chars)
    reports: list[EvaluatorReport] = []
    raws: list[str] = []

    for bi, (s, e) in enumerate(ranges):
        batch = chapters[s:e]
        nos = [c["no"] for c in batch]
        note = f"本批第 {nos[0]}–{nos[-1]} 章（共 {len(batch)} 章）"
        if s > 0:
            note += f"；前 {min(overlap, len(batch))} 章与上一批重叠，用于衔接判断"
        msgs = build_daemon_criteria_batch_messages(
            criteria_lines, batch, prev_feedback, batch_note=note,
        )
        try:
            res = client.chat_with_continuation(
                msgs, target_words=target_words,
                max_total_tokens=16000, temperature=0.3,
            )
        except Exception as exc:  # 单批失败不该炸掉整轮评估
            if on_progress:
                on_progress(bi, len(ranges), None, error=str(exc))
            continue
        raw = (res.content or "").strip()
        raws.append(f"=== batch {bi + 1}/{len(ranges)} ch{nos[0]}-{nos[-1]} ===\n{raw}")
        json_text = _extract_json_block(raw)
        if not json_text:
            continue
        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError:
            continue
        rep = _parse_report(parsed)
        rep.raw_text = raw
        # 只信本批真实出现过的章号——LLM 编的章号一律丢掉，否则 surgical 会去
        # 重写一个不存在的章
        valid = set(nos)
        for c in rep.criteria:
            c.failed_chapters = [n for n in c.failed_chapters if n in valid]
            if not c.passed and not c.failed_chapters:
                # 说没过却指不出章：保守起见记整批，避免漏重写
                c.failed_chapters = list(nos)
        # 顶层 failed_chapters 必须包含各 criterion 的章号——LLM 常在顶层漏填，
        # 只信顶层会把「整批待重写」的保守回填吃掉，surgical 就漏章了
        crit_chapters: set[int] = set()
        for c in rep.criteria:
            crit_chapters |= set(c.failed_chapters)
        rep.failed_chapters = sorted((set(rep.failed_chapters) | crit_chapters) & valid)
        if on_progress:
            on_progress(bi, len(ranges), rep)
        reports.append(rep)

    if not reports:
        # fail-safe：一个批都没解析出可用的 JSON 绝不能报「全通过」，
        # 否则 daemon 会误判达标直接退出，白烧一轮生成 quota
        return EvaluatorReport(
            summary=f"分块评估失败：{len(ranges)} 批全部未产出可解析 JSON",
            all_passed=False,
            raw_text="\n\n".join(raws),
        )

    agg = _aggregate_batch_reports(reports, ranges, criteria_lines)
    agg.raw_text = "\n\n".join(raws)
    return agg


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
