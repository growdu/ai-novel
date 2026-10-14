"""novel-writer Web 仪表盘。

提供一个轻量级 HTTP 服务器（纯 stdlib），内嵌 HTML/JS 单页仪表盘，
让用户在浏览器里查看 novel auto 的实时进度。

特性：
- 零依赖（Python 标准库 http.server）
- 自动轮询 .novel/auto_state.json
- 实时进度条 / 累计成本 / token / 章节状态表
- 暂停 / 恢复控制：POST /api/control 写 .novel/auto_control.json
- 单 HTML 文件，无外部资源，离线可访问

用法：
    novel serve [PORT]        # 默认 8765
    novel serve --port 9000
    novel auto ... --serve    # auto 完成后自动打开浏览器
"""
from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# 控制信号协议
# ---------------------------------------------------------------------------

class ControlSignal:
    """用户在仪表盘发的指令：写到 .novel / .novel/auto_control.json。"""

    RUN = "run"            # 默认：继续
    PAUSE = "pause"        # 在当前章节写完后停下
    STOP = "stop"          # 在下一章前停下，并退出整个流程
    DOWNGRADE = "downgrade"  # 立即降级到 draft 档

    @classmethod
    def write(cls, project_dir: Path, signal: str) -> Path:
        from novel.storage import PROJECT_DIR
        path = project_dir / PROJECT_DIR / "auto_control.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"signal": signal, "at": __import__("time").time()}, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    @classmethod
    def read(cls, project_dir: Path) -> str:
        from novel.storage import PROJECT_DIR
        path = project_dir / PROJECT_DIR / "auto_control.json"
        if not path.exists():
            return cls.RUN
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("signal", cls.RUN)
        except Exception:
            return cls.RUN

    @classmethod
    def clear(cls, project_dir: Path) -> None:
        from novel.storage import PROJECT_DIR
        path = project_dir / PROJECT_DIR / "auto_control.json"
        if path.exists():
            path.unlink()


# ---------------------------------------------------------------------------
# HTTP 处理器
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>novel-writer · auto</title>
<style>
  body { font-family: ui-monospace, SFMono-Regular, "Cascadia Mono", Menlo, monospace;
         background: #fafafa; color: #222; padding: 20px; max-width: 800px;
         margin: 0 auto; line-height: 1.4; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  h2 { font-size: 12px; color: #888; font-weight: normal; margin: 0 0 16px; }
  .meta { font-size: 11px; color: #999; margin-bottom: 16px; }
  .cards { display: grid; grid-template-columns: repeat(4, 1fr);
           gap: 12px; margin-bottom: 16px; }
  .card { background: white; border: 1px solid #e5e5e5;
          border-radius: 4px; padding: 12px; }
  .card-label { font-size: 11px; color: #888; }
  .card-value { font-size: 20px; font-weight: 600; margin-top: 2px; }
  .card-sub { font-size: 11px; color: #999; margin-top: 2px; }
  .bar { background: #e5e5e5; height: 18px; border-radius: 2px; margin: 6px 0;
         overflow: hidden; }
  .bar-fill { background: #4a9eff; height: 100%; color: white; font-size: 11px;
              display: flex; align-items: center; justify-content: center; }
  table { width: 100%; border-collapse: collapse; margin-top: 12px;
          background: white; border: 1px solid #e5e5e5;
          border-radius: 4px; font-size: 12px; }
  th, td { padding: 6px 10px; text-align: left; }
  th { background: #f5f5f5; color: #666; font-weight: 600; }
  td { border-top: 1px solid #f0f0f0; }
  tr.failed { color: #c00; }
  tr.done { color: #080; }
  .controls { margin: 12px 0; }
  button { padding: 6px 12px; border: 1px solid #ccc; background: white;
           font-family: inherit; font-size: 12px; cursor: pointer;
           margin-right: 4px; border-radius: 3px; }
  button:hover { background: #f5f5f5; }
  button.stop { color: #c00; border-color: #c00; }
  .badge { display: inline-block; padding: 1px 6px; border-radius: 2px;
           font-size: 10px; }
  .badge-done { background: #dfd; color: #040; }
  .badge-running { background: #def; color: #048; }
  .badge-failed { background: #fdd; color: #400; }
  .badge-pending { background: #eee; color: #666; }
  .error { color: #c00; font-size: 12px; }
</style>
</head>
<body>
<h1 id="title">novel-writer auto</h1>
<h2>阶段: <span id="phase">-</span></h2>
<div class="meta">
  <span id="meta-path"></span> · <span id="meta-time">-</span>
</div>

<div class="cards">
  <div class="card">
    <div class="card-label">进度</div>
    <div class="card-value" id="progress-value">-</div>
    <div class="bar"><div class="bar-fill" id="progress-fill" style="width:0%">0%</div></div>
  </div>
  <div class="card">
    <div class="card-label">字数</div>
    <div class="card-value" id="card-words">-</div>
  </div>
  <div class="card">
    <div class="card-label">Token</div>
    <div class="card-value" id="card-tokens">-</div>
    <div class="card-sub" id="card-tokens-split">-</div>
  </div>
  <div class="card">
    <div class="card-label">成本</div>
    <div class="card-value" id="card-cost">-</div>
    <div class="card-sub" id="card-budget">-</div>
  </div>
</div>

<div class="controls">
  <button id="btn-pause">暂停</button>
  <button id="btn-resume">继续</button>
  <button id="btn-downgrade">降级</button>
  <button class="stop" id="btn-stop">停止</button>
</div>

<table>
<thead>
<tr><th>章</th><th>状态</th><th>字</th><th>AI</th><th>雷达</th><th>耗时</th></tr>
</thead>
<tbody id="chapter-tbody"></tbody>
</table>

<div id="error-msg" class="error"></div>

<script>
function badge(s) {
  return '<span class="badge badge-' + s + '">' + s + '</span>';
}
async function fetchState() {
  try {
    const r = await fetch('/api/state');
    const s = await r.json();
    if (s.error) {
      document.getElementById('error-msg').textContent = s.error;
      return;
    }
    document.getElementById('error-msg').textContent = '';
    document.getElementById('title').textContent = (s.spec.title || '?') + ' · novel-writer auto';
    document.getElementById('phase').textContent = s.phase;
    document.getElementById('meta-path').textContent = s.project_root || '';
    document.getElementById('meta-time').textContent = new Date().toLocaleTimeString();

    const done = s.chapters_done_count || 0;
    const total = s.chapters_total || 0;
    document.getElementById('progress-value').textContent = done + ' / ' + total;
    const pct = total ? Math.round(done * 100 / total) : 0;
    document.getElementById('progress-fill').style.width = pct + '%';
    document.getElementById('progress-fill').textContent = pct + '%';

    document.getElementById('card-words').textContent = (s.total_words || 0).toLocaleString();
    document.getElementById('card-tokens').textContent = (s.cumulative_tokens || 0).toLocaleString();
    document.getElementById('card-tokens-split').textContent = s.cumulative_prompt_tokens
      ? 'in ' + s.cumulative_prompt_tokens.toLocaleString() + ' / out ' + s.cumulative_completion_tokens.toLocaleString()
      : '-';
    document.getElementById('card-cost').textContent = '¥' + (s.cumulative_cost_cny || 0).toFixed(2);
    document.getElementById('card-budget').textContent = s.budget_cny > 0
      ? '预算 ¥' + s.budget_cny.toFixed(2) + ' · ' + Math.max(0, Math.round((1 - s.cumulative_cost_cny / s.budget_cny) * 100)) + '% 余'
      : '无限制';

    const tbody = document.getElementById('chapter-tbody');
    tbody.innerHTML = (s.chapters || []).map(ch => {
      const cls = ch.status === 'generated' || ch.status === 'polished' ? 'done' :
                  ch.status === 'failed' ? 'failed' : 'pending';
      const elapsed = ch.elapsed_ms ? Math.round(ch.elapsed_ms / 60000) + 'min' : '-';
      return '<tr class="' + cls + '"><td>' + ch.chapter_no + '</td>'
        + '<td>' + badge(ch.status || 'pending') + '</td>'
        + '<td>' + (ch.word_count || 0) + '</td>'
        + '<td>' + (ch.ai_flavor != null ? ch.ai_flavor : '-') + '</td>'
        + '<td>' + (ch.radar != null ? ch.radar : '-') + '</td>'
        + '<td>' + elapsed + '</td></tr>';
    }).join('');
  } catch (e) {
    document.getElementById('error-msg').textContent = e.message;
  }
}
async function ctrl(sig) {
  await fetch('/api/control', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({signal: sig}),
  });
  fetchState();
}
document.getElementById('btn-pause').onclick = () => ctrl('pause');
document.getElementById('btn-resume').onclick = () => ctrl('run');
document.getElementById('btn-downgrade').onclick = () => ctrl('downgrade');
document.getElementById('btn-stop').onclick = () => ctrl('stop');
fetchState();
setInterval(fetchState, 2000);
</script>
</body>
</html>
"""


def build_state_payload(project_dir: Path) -> dict:
    """读取 .novel/auto_state.json + 元数据，返回给前端的 payload。"""
    from novel.auto_state import AutoState, Phase
    from novel.storage import PROJECT_DIR

    state_path = project_dir / PROJECT_DIR / "auto_state.json"
    project_yaml = project_dir / PROJECT_DIR / "project.yaml"

    if not state_path.exists():
        # 没有 state：返回空
        try:
            import yaml
            proj = yaml.safe_load(project_yaml.read_text(encoding="utf-8")) if project_yaml.exists() else {}
        except Exception:
            proj = {}
        return {
            "project_root": str(project_dir),
            "spec": {"title": proj.get("title", project_dir.name)},
            "phase": "未启动",
            "chapters_done_count": 0,
            "chapters_total": 0,
            "chapters_failed_count": 0,
            "total_words": 0,
            "chapters": [],
            "error": None,
        }

    state = AutoState.load(project_dir)
    if state is None:
        return {"project_root": str(project_dir), "error": "状态文件损坏"}

    # 序列化 chapter_results
    chapters = []
    for n in range(1, state.chapters_total + 1):
        r = state.chapter_results.get(n)
        if r is None:
            chapters.append({"chapter_no": n, "status": "pending"})
        else:
            chapters.append({
                "chapter_no": r.chapter_no,
                "status": r.status,
                "word_count": r.word_count,
                "iterations": r.iterations,
                "total_tokens": r.total_tokens,
                "ai_flavor": r.ai_flavor,
                "radar": r.radar,
                "elapsed_ms": r.elapsed_ms,
            })

    return {
        "project_root": str(project_dir),
        "spec": state.spec,
        "phase": state.phase.value,
        "chapters_done_count": len(state.chapters_done),
        "chapters_total": state.chapters_total,
        "chapters_failed_count": len(state.chapters_failed),
        "total_words": state.total_words,
        "cumulative_tokens": state.cumulative_tokens,
        "cumulative_prompt_tokens": state.cumulative_prompt_tokens,
        "cumulative_completion_tokens": state.cumulative_completion_tokens,
        "cumulative_cost_cny": state.cumulative_cost_cny,
        "budget_cny": state.budget_cny,
        "elapsed_s": state.updated_at - state.started_at,
        "model": state.spec.get("model", ""),
        "planning_files_count": len(state.planning_files),
        "chapters": chapters,
    }


def make_handler(project_dir: Path):
    """工厂：根据 project_dir 创建 HTTP handler。"""
    project_dir = project_dir.resolve()

    class DashboardHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            """静音访问日志。"""
            return

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send_html(DASHBOARD_HTML)
            elif path == "/api/state":
                payload = build_state_payload(project_dir)
                self._send_json(payload)
            elif path == "/health":
                self._send_json({"ok": True, "project": str(project_dir)})
            else:
                self.send_error(404)

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/api/control":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                try:
                    data = json.loads(body) if body else {}
                    signal = data.get("signal", "run")
                    ControlSignal.write(self.project_dir, signal)
                    self._send_json({"ok": True, "signal": signal})
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, status=400)
            else:
                self.send_error(404)

        # ---- helpers ----
        @property
        def project_dir(self):
            return project_dir

        def _send_html(self, content: str):
            data = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload, status: int = 200):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    return DashboardHandler


def serve(project_dir: Path, port: int = 8765, open_browser: bool = False) -> ThreadingHTTPServer:
    """启动 Web 仪表盘服务器（阻塞）。"""
    handler = make_handler(project_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    return server


def serve_background(project_dir: Path, port: int = 8765, open_browser: bool = False) -> ThreadingHTTPServer:
    """启动后台线程运行服务器（不阻塞）。"""
    server = serve(project_dir, port=port, open_browser=open_browser)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server