"""LLM 调用层。
兼容 OpenAI Chat Completions 协议：minimax / OpenAI / DeepSeek 等都支持。
"""
from __future__ import annotations

import json
import time
import re
from dataclasses import dataclass, field
from typing import Iterable

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
    # 如果未闭合 <think> 残片还在，从 <think> 开始到结尾全部剥掉
    if "<think>" in text:
        idx = text.find("<think>")
        text = text[:idx]
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


class LLMClient:
    def __init__(self, cfg: GlobalConfig | None = None):
        self.cfg = cfg or GlobalConfig()

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
                raise LLMError("api " + str(resp.status_code) + ": " + resp.text[:400])
            data = resp.json()
            content = (
                data.get("choices", [{}])[0].get("message", {}).get("content", "")
            )
            content = _strip_think_tags(content)
            usage = data.get("usage", {}) or {}
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
            looks_substantial = len(tail_stripped) > 800
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
