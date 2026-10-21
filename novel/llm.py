"""LLM 调用层。
兼容 OpenAI Chat Completions 协议：minimax / OpenAI / DeepSeek 等都支持。
"""
from __future__ import annotations

import json
import time
import re
from dataclasses import dataclass, field

import requests

from .config import GlobalConfig

_THINK_TAG_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")
_PARTIAL_THINK_RE = re.compile(r"<think>[\s\S]*?(?=\n\n##|\n\n[^#]|\Z)", re.IGNORECASE)

def _strip_think_tags(text):
    if not text:
        return text
    text = _THINK_TAG_RE.sub("", text)
    text = _PARTIAL_THINK_RE.sub("", text)
    if "<think>" in text:
        idx = text.find("<think>")
        text = text[:idx]
    # 如果开头是英文 think 残片（"OK" "Let me" "So" "Now" 等）且 200 字符内出现 markdown 标题，从标题开始截断
    import re as _re
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("## ") or s.startswith("# "):
            # 找到首个标题，把之前的内容当作 think 残片扔掉
            if i > 0 and i < 15:
                head = "\n".join(lines[:i])
                if _re.search(r"\bok\b|\blet me\b|\bso\b|\bnow\b|\bfirst\b|\bthe user\b|\bmodel\b|\bI should\b|\bnotice\b|\bwriting\b", head.lower()):
                    text = "\n".join(lines[i:])
                    break
    return text.strip()

def _try_parse_json(text):
    text = _strip_think_tags(text or "")
    m = _JSON_BLOCK_RE.search(text)
    if m:
        text = m.group(1)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return {"_raw": text, "_error": "json parse failed"}


@dataclass
class Message:
    role: str
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResult:
    content: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    elapsed_ms: int = 0
    raw: dict = field(default_factory=dict)


class LLMError(RuntimeError):
    pass


class RateLimitError(LLMError):
    """LLM 服务配额/速率限制（minimax 5 小时/W 周用量；OpenAI TPM/RPM）。

    携带让上层（auto.py 配额 handler）能优雅等待并重试的元数据：
      - reset_at: 何时可恢复（绝对 Unix 时间戳；0 表示不可推断）
      - retry_after_seconds: 服务器建议等待秒数（0 表示未告知）
      - raw_status / raw_text: 原始响应方便调试
    """

    def __init__(self, message: str, reset_at: int = 0, retry_after_seconds: int = 0,
                 raw_status: int = 0, raw_text: str = ""):
        super().__init__(message)
        self.reset_at = reset_at
        self.retry_after_seconds = retry_after_seconds
        self.raw_status = raw_status
        self.raw_text = raw_text


# 检测 429 / 配额文本
_RATE_LIMIT_PATTERNS = [
    re.compile(r"insufficient[_ ]?quota", re.IGNORECASE),
    re.compile(r"rate[_ ]?limit[_ ]?(exceeded|reached)", re.IGNORECASE),
    re.compile(r"\bRPM\b.*(?:limit|exceeded|reached)", re.IGNORECASE),
    re.compile(r"\bTPM\b.*(?:limit|exceeded|reached)", re.IGNORECASE),
    re.compile(r"配额", re.UNICODE),                       # 配额
    re.compile(r"余额不足", re.UNICODE),           # 余额不足
    re.compile(r"5\s*小时.{0,8}限额", re.UNICODE),  # 5小时限额
    re.compile(r"周.{0,8}用量.{0,8}限额", re.UNICODE),  # 周用量限额
    re.compile(r"请求过快", re.UNICODE),           # 请求过快
]


def _is_rate_limit_response(status_code: int, text: str, headers) -> bool:
    """判断 HTTP 响应是否为配额/速率限制。

    触发条件（满足任一即返回 True）：
      1. status_code == 429 (Too Many Requests)
      2. status_code == 403 + 含 "quota" / "billing" / "余额" 等付费类关键词
      3. text 命中已知的配额模式（见 _RATE_LIMIT_PATTERNS）
    """
    if status_code == 429:
        return True
    if status_code == 403 and re.search(r"quota|billing|余额|账户", text, re.IGNORECASE):
        return True
    for p in _RATE_LIMIT_PATTERNS:
        if p.search(text):
            return True
    return False


def _parse_retry_after(headers) -> int:
    """从响应头解析 Retry-After（秒）。返回 0 表示不可推断。"""
    # requests.headers 是 CaseInsensitiveDict
    val = headers.get("Retry-After") if headers else None
    if not val:
        return 0
    try:
        return max(0, int(val))
    except (TypeError, ValueError):
        # 也可能是 HTTP-date 格式；这里简化只处理秒数
        return 0


def _build_rate_limit_error(status_code: int, text: str, headers) -> RateLimitError:
    retry_after = _parse_retry_after(headers)
    # 启发式估算 reset_at：仅当 retry_after 已知
    import time as _t
    reset_at = int(_t.time() + retry_after) if retry_after > 0 else 0
    msg = "rate limit: " + str(status_code) + " retry_after=" + str(retry_after) + "s body=" + text[:200]
    return RateLimitError(
        message=msg,
        reset_at=reset_at,
        retry_after_seconds=retry_after,
        raw_status=status_code,
        raw_text=text[:400],
    )


class LLMClient:
    def __init__(self, cfg: GlobalConfig | None = None):
        self.cfg = cfg or GlobalConfig()
        # 累计用量：auto.py 靠这些属性做成本统计与 budget 护栏。
        # 单次调用的用量在 LLMResult 上，长跑编排需要的是跨调用累计值。
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

    def token_snapshot(self) -> tuple[int, int, int]:
        """当前累计 (prompt, completion, total)，用于按章取增量。"""
        return (self.prompt_tokens, self.completion_tokens, self.total_tokens)

    def _accumulate_usage(self, usage: dict) -> None:
        """把一次调用的 usage 并入累计计数。只有真正拿到响应才调用。"""
        self.prompt_tokens += usage.get("prompt_tokens", 0) or 0
        self.completion_tokens += usage.get("completion_tokens", 0) or 0
        self.total_tokens += usage.get("total_tokens", 0) or 0

    def chat(self, messages, temperature=None, top_p=None, max_tokens=None, stop=None, retry=3):
        if self.cfg.dry_run:
            return self._dry_run(messages)
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": "Bearer " + self.cfg.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.cfg.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "top_p": self.cfg.top_p if top_p is None else top_p,
            "max_tokens": self.cfg.max_tokens if max_tokens is None else max_tokens,
        }
        if stop:
            payload["stop"] = stop
        # minimax-M3 等推理模型需要在 reasoning_content 与 content 之间解耦：
        # API 返回时 content 已经包含 <think>...</think>\u8fd9\u4e9b\u6807\u7b7e\u3002\u6211\u4eec\u5728\u8fd9\u91cc\u5269\u4e0b\u4e1a\u52a1\u8bed\u4e49\u3002
        last_err = None
        for attempt in range(retry):
            t0 = time.time()
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.cfg.request_timeout,
                )
            except requests.RequestException as e:
                last_err = e
                time.sleep(min(2 ** attempt, 8))
                continue
            elapsed = int((time.time() - t0) * 1000)
            if resp.status_code >= 500:
                last_err = LLMError("server " + str(resp.status_code) + ": " + resp.text[:200])
                time.sleep(min(2 ** attempt, 8))
                continue
            if resp.status_code != 200:
                # 先检测是否为配额/速率限制（minimax 5小时/W 周用量；OpenAI TPM/RPM）
                if _is_rate_limit_response(resp.status_code, resp.text, resp.headers):
                    raise _build_rate_limit_error(resp.status_code, resp.text, resp.headers)
                raise LLMError("api " + str(resp.status_code) + ": " + resp.text[:400])
            data = resp.json()
            content = (
                data.get("choices", [{}])[0].get("message", {}).get("content", "")
            )
            content = _strip_think_tags(content)
            usage = data.get("usage", {}) or {}
            self._accumulate_usage(usage)
            return LLMResult(
                content=content,
                model=data.get("model", self.cfg.model),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                elapsed_ms=elapsed,
                raw=data,
            )
        raise LLMError("chat failed after retries: " + repr(last_err))

    def chat_json(self, messages, **kwargs):
        """\u8c03\u7528 LLM \u5e76\u8981\u6c42\u8fd4\u56de JSON\u3002\u9002\u7528\u4e8e\u8981\u6c42\u6a21\u578b\u8f93\u51fa\u7ed3\u6784\u5316\u6570\u636e\u7684\u573a\u666f\u3002"""
        kwargs.setdefault("temperature", 0.4)
        res = self.chat(messages, **kwargs)
        return _try_parse_json(res.content)

    def continue_generate(self, messages, partial, target_words, **kwargs):
        """\u63a5\u7eed\u751f\u6210\uff1a\u5728 partial \u540e\u9762\u63a5\u7740\u5199\u3002"""
        new_msgs = list(messages) + [
            Message("assistant", partial),
            Message(
                "user",
                "\u8bf7\u4ece\u4e0a\u9762\u90a3\u4e2a\u53e5\u5b50\u63a5\u7740\u5199\u4e0b\u53bb\u3002\u4e0d\u8981\u91cd\u590d\u5df2\u5199\u5185\u5bb9\uff0c\u4e0d\u8981\u603b\u7ed3\u3002\u518d\u5199\u5927\u7ea6 " + str(target_words) + " \u5b57\u3002\u8d8a\u63a5\u8d8a\u597d\uff0c\u4fdd\u8bc1\u8854\u63a5\u987a\u7545\u3002",
            ),
        ]
        kwargs.setdefault("temperature", 0.95)
        return self.chat(new_msgs, **kwargs)


    def chat_with_continuation(self, messages, target_words=1000, max_total_tokens=30000, temperature=None, verbose=False, **kwargs):
        """能自动续写的 chat：finish_reason=length 时接着生成，最后拼接返回。"""
        kwargs.setdefault("temperature", 0.95 if temperature is None else temperature)
        chunks = []
        cur_msgs = list(messages)
        total_tokens = 0
        iters = 0
        last_result = None
        while iters < 4:
            kwargs.setdefault("max_tokens", min(max_total_tokens - total_tokens, 16000))
            if kwargs["max_tokens"] < 1500:
                break
            res = self.chat(cur_msgs, **kwargs)
            last_result = res
            total_tokens += res.total_tokens or 0
            chunks.append(res.content)
            iters += 1
            fr = res.raw.get("choices", [{}])[0].get("finish_reason", "stop") if res.raw else "stop"
            content = res.content
            content = _strip_think_tags(content)
            tail_stripped = content.rstrip()
            think_residue = "<think>" in content or " 区块" in content
            min_chars = max(200, int((target_words or 1000) * 0.6))
            looks_substantial = len(tail_stripped) >= min_chars
            looks_complete = (fr == "stop" and looks_substantial) or (tail_stripped.endswith(("。", "?", "!", "？", "！", "——")) and looks_substantial)
            if looks_complete and not think_residue:
                break
            if verbose:
                print(f"[continue] iter {iters}: len={len(content)}, fr={fr}, will continue")
            cur_msgs = list(messages) + [Message("assistant", "\n".join(chunks))]
            cur_msgs.append(Message("user", "接着写。不要重复、不要总结。再写大约 " + str(target_words) + " 字。"))
            kwargs.pop("max_tokens", None)
        merged = "\n".join(chunks)
        if last_result is None:
            return last_result
        last_result.content = merged
        last_result.raw["_continue_iters"] = iters
        return last_result

    def stream_chat(self, messages, temperature=None, top_p=None, max_tokens=None):
        if self.cfg.dry_run:
            yield "[DRY_RUN] " + messages[-1].content[:200]
            return
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": "Bearer " + self.cfg.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.cfg.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "top_p": self.cfg.top_p if top_p is None else top_p,
            "max_tokens": self.cfg.max_tokens if max_tokens is None else max_tokens,
            "stream": True,
        }
        with requests.post(
            url, headers=headers, json=payload, timeout=self.cfg.request_timeout, stream=True
        ) as resp:
            if resp.status_code != 200:
                if _is_rate_limit_response(resp.status_code, resp.text, resp.headers):
                    raise _build_rate_limit_error(resp.status_code, resp.text, resp.headers)
                raise LLMError("stream " + str(resp.status_code) + ": " + resp.text[:300])
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith(b"data:"):
                    line = line[len(b"data:"):].strip()
                if line == b"[DONE]":
                    break
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
                if delta:
                    yield delta

    def _dry_run(self, messages):
        head = "=" * 60
        print("\n" + head + "\n[DRY_RUN] 将要发送的消息 (n=" + str(len(messages)) + "):")
        for i, m in enumerate(messages):
            print("\n--- [" + str(i) + "] role=" + m.role + " ---")
            print(m.content[:1200] + ("..." if len(m.content) > 1200 else ""))
        print("\n" + head + "\n")
        placeholder = "[DRY_RUN 模式：无 API 调用，请在 .env 中设置 DRY_RUN=false]\n\n"
        return LLMResult(content=placeholder, model="dry-run", elapsed_ms=0)
