"""全局配置：读取环境变量、.novel.yaml 工程配置文件。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except ImportError:
    def _manual_load_env():
        p = Path.cwd()
        for cand in [p / ".env", p.parent / ".env"]:
            if cand.exists():
                for line in cand.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
                return
    _manual_load_env()


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)) or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)) or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = (_env(name) or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


@dataclass
class GlobalConfig:
    """运行时全局配置（可被项目配置覆盖）。"""

    base_url: str = field(
        default_factory=lambda: _env("OPENAI_BASE_URL", "https://api.minimaxi.com/v1") or ""
    )
    api_key: str = field(
        default_factory=lambda: _env("OPENAI_API_KEY", "") or ""
    )
    model: str = field(
        default_factory=lambda: _env("OPENAI_MODEL", "minimax-Text-01") or "minimax-Text-01"
    )
    temperature: float = field(default_factory=lambda: _env_float("TEMPERATURE", 0.9))
    top_p: float = field(default_factory=lambda: _env_float("TOP_P", 0.95))
    max_tokens: int = field(default_factory=lambda: _env_int("MAX_TOKENS", 4096))
    target_chapter_words: int = field(
        default_factory=lambda: _env_int("TARGET_CHAPTER_WORDS", 3000)
    )
    dry_run: bool = field(default_factory=lambda: _env_bool("DRY_RUN", False))
    request_timeout: int = field(default_factory=lambda: _env_int("REQUEST_TIMEOUT", 180))

    def masked(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        if d.get("api_key"):
            d["api_key"] = d["api_key"][:4] + "***" + d["api_key"][-3:]
        return d


def load_global() -> GlobalConfig:
    """加载全局配置：每次调用都重新读取 .env（不依赖 dotenv 包）。"""
    p = Path.cwd()
    for cand in [p / ".env", p.parent / ".env"]:
        if cand.exists():
            for line in cand.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()
            break
    return GlobalConfig()


def find_project_root(start: Path | None = None) -> Path | None:
    """从当前目录向上查找包含 .novel 目录的项目根。"""
    p = (start or Path.cwd()).resolve()
    for parent in [p, *p.parents]:
        if (parent / ".novel").is_dir():
            return parent
    return None
