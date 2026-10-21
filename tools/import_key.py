"""把 key 从临时文件导入内核 .env，并做一次连通性自测。

key 值全程不打印，只报告「已写入 / 长度是否合理 / 连通是否成功」。
临时文件在读取后立即删除。

用法：
    python3 tools/import_key.py --from-file /tmp/yuzhou_key.txt
    python3 tools/import_key.py --from-file ... --base-url https://.../v1 --model xxx
    python3 tools/import_key.py --probe            # 只看当前 .env 是否已配好
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / ".env"
TMP = Path("/tmp/yuzhou_key.txt")

# 允许覆写的字段
FIELDS = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL")


def read_key(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"找不到 key 文件：{path}")
    key = path.read_text(encoding="utf-8").strip()
    if len(key) < 20:
        raise SystemExit("key 长度异常，疑似文件内容不对")
    path.unlink()  # 读完即删
    return key


def update_env(values: dict[str, str]) -> list[str]:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    changed = []
    for key, val in values.items():
        if not val:
            continue
        for i, ln in enumerate(lines):
            if ln.split("=", 1)[0].strip() == key:
                lines[i] = f"{key}={val}"
                break
        else:
            lines.append(f"{key}={val}")
        changed.append(key)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def self_test() -> bool:
    sys.path.insert(0, str(REPO))
    from novel.config import load_global
    from novel.llm import LLMClient, Message

    cfg = load_global()
    print(f"  载入：model={cfg.model}  base={cfg.base_url}")
    try:
        r = LLMClient(cfg).chat(
            [Message(role="user", content="只回答两个字：正常")], max_tokens=64
        )
        text = (r.content or "").strip()
        print(f"  连通性：OK → 模型回复「{text[:30]}」")
        return True
    except Exception as e:
        print(f"  连通性：失败 → {str(e)[:220]}")
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-file", help="存放 key 的临时文件（读取后删除）")
    ap.add_argument("--base-url", default="", help="同时改写 OPENAI_BASE_URL")
    ap.add_argument("--model", default="", help="同时改写 OPENAI_MODEL")
    ap.add_argument("--probe", action="store_true", help="不写文件，只按当前 .env 自测")
    ap.add_argument("--no-test", action="store_true")
    args = ap.parse_args()

    if not args.probe:
        if not args.from_file:
            raise SystemExit("要给 --from-file 或 --probe")
        src = Path(args.from_file) if args.from_file != "default" else TMP
        key = read_key(src)
        vals = {"OPENAI_API_KEY": key}
        if args.base_url:
            vals["OPENAI_BASE_URL"] = args.base_url
        if args.model:
            vals["OPENAI_MODEL"] = args.model
        print(f"✓ 已写入 .env：{', '.join(update_env(vals))}（key 值不显示）")
    else:
        print("按当前 .env 自测：")

    if not args.no_test:
        ok = self_test()
        if not ok and not args.probe:
            print(
                "\n  key 格式与当前 base_url 可能不匹配。\n"
                "  如果这是第三方中转/代理服务的 key，请补上它的 base_url：\n"
                "    python3 tools/import_key.py --from-file <新key文件> --base-url https://<域名>/v1 --model <模型名>"
            )


if __name__ == "__main__":
    main()