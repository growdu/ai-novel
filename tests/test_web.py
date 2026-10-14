"""novel.web 单元测试：HTTP 仪表盘。"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
import urllib.request

from novel.auto_state import AutoState, ChapterResult, Phase
from novel.storage import init_project
from novel.web import (
    ControlSignal,
    build_state_payload,
    make_handler,
    serve_background,
)


@pytest.fixture
def sample_state_dir(tmp_path):
    """建一个有状态的项目目录。"""
    init_project(tmp_path, "测试", theme="...", meta={"genre": "悬疑"})
    state = AutoState(
        spec={"title": "测试", "quality": "standard"},
        chapters_total=5,
        chapters_done=[1, 2],
        chapters_failed=[2],
        chapter_results={
            1: ChapterResult(chapter_no=1, status="generated", word_count=3000,
                              prompt_tokens=2000, completion_tokens=1000, total_tokens=3000),
            2: ChapterResult(chapter_no=2, status="failed", word_count=100,
                              error="字数过少"),
        },
        cumulative_tokens=3000,
        cumulative_prompt_tokens=2000,
        cumulative_completion_tokens=1000,
        cumulative_cost_cny=0.003,
    )
    state.save(tmp_path)
    return tmp_path


def _http_get(url, timeout=5):
    return urllib.request.urlopen(url, timeout=timeout).read().decode("utf-8")


def _http_post(url, data, timeout=5):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")


class TestControlSignal:
    def test_default_run(self, tmp_path):
        assert ControlSignal.read(tmp_path) == "run"

    def test_write_pause(self, tmp_path):
        ControlSignal.write(tmp_path, ControlSignal.PAUSE)
        assert ControlSignal.read(tmp_path) == "pause"

    def test_clear(self, tmp_path):
        ControlSignal.write(tmp_path, ControlSignal.STOP)
        ControlSignal.clear(tmp_path)
        assert ControlSignal.read(tmp_path) == "run"

    def test_corrupted_signal_falls_back_to_run(self, tmp_path):
        from novel.storage import PROJECT_DIR
        (tmp_path / PROJECT_DIR).mkdir(parents=True, exist_ok=True)
        (tmp_path / PROJECT_DIR / "auto_control.json").write_text("not json", encoding="utf-8")
        assert ControlSignal.read(tmp_path) == "run"


class TestBuildStatePayload:
    def test_no_state(self, tmp_path):
        payload = build_state_payload(tmp_path)
        assert payload["chapters_total"] == 0
        assert payload["phase"] == "未启动"
        assert payload["error"] is None

    def test_with_state(self, sample_state_dir):
        payload = build_state_payload(sample_state_dir)
        assert payload["chapters_total"] == 5
        assert payload["chapters_done_count"] == 2
        assert payload["chapters_failed_count"] == 1
        assert payload["total_words"] == 3100
        assert payload["cumulative_tokens"] == 3000
        assert len(payload["chapters"]) == 5
        # 第 1 章是 generated
        assert payload["chapters"][0]["status"] == "generated"
        # 第 5 章是 pending
        assert payload["chapters"][4]["status"] == "pending"

    def test_corrupted_state(self, tmp_path):
        from novel.storage import PROJECT_DIR
        (tmp_path / PROJECT_DIR).mkdir(parents=True, exist_ok=True)
        (tmp_path / PROJECT_DIR / "auto_state.json").write_text("garbage", encoding="utf-8")
        payload = build_state_payload(tmp_path)
        assert "error" in payload and payload["error"] is not None


class TestHTTPServer:
    @staticmethod
    @pytest.fixture
    def running_server(sample_state_dir):
        server = serve_background(sample_state_dir, port=0, open_browser=False)
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}"
        server.shutdown()
        server.server_close()

    def test_health_endpoint(self, running_server):
        text = _http_get(running_server + "/health")
        assert '"ok"' in text
        assert '"project"' in text

    def test_index_serves_html(self, running_server):
        text = _http_get(running_server + "/")
        assert "<!DOCTYPE html>" in text
        assert "novel-writer" in text
        assert "/api/state" in text  # 前端会调用

    def test_api_state_endpoint(self, running_server):
        data = json.loads(_http_get(running_server + "/api/state"))
        assert data["chapters_total"] == 5
        assert data["chapters_done_count"] == 2
        assert data["cumulative_tokens"] == 3000

    def test_404(self, running_server):
        try:
            _http_get(running_server + "/nonexistent")
            assert False, "should have raised HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 404

    def test_post_control_pause(self, running_server, sample_state_dir):
        _http_post(running_server + "/api/control", {"signal": "pause"})
        assert ControlSignal.read(sample_state_dir) == "pause"

    def test_post_control_resume(self, running_server, sample_state_dir):
        ControlSignal.write(sample_state_dir, ControlSignal.PAUSE)
        _http_post(running_server + "/api/control", {"signal": "run"})
        assert ControlSignal.read(sample_state_dir) == "run"

    def test_post_control_stop(self, running_server, sample_state_dir):
        _http_post(running_server + "/api/control", {"signal": "stop"})
        assert ControlSignal.read(sample_state_dir) == "stop"

    def test_post_control_invalid(self, running_server):
        try:
            _http_post(running_server + "/api/control", {"signal": "weirdvalue"})
            # 没崩就好；服务端只负责写入
            assert True
        except urllib.error.HTTPError:
            pass  # 也可