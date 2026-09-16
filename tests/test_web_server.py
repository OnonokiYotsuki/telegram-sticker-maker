import io
import os
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from PIL import Image
import pytest

from server.api import AppAPI
from server.stream_server import LocalStreamServer, start_stream_server


@pytest.fixture(scope="module")
def web_server():
    server = start_stream_server(port=0)
    yield server
    server.stop()


def test_server_health(web_server):
    url = f"{web_server.get_url()}/health"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        content = resp.read().decode("utf-8")
        assert "ok" in content


def test_server_static_dist(web_server):
    # Test index.html serving
    url = web_server.get_url("/")
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        content = resp.read().decode("utf-8")
        assert "Telegram Sticker Maker" in content or "vite" in content or "<html" in content


def test_server_thumbnail_generation(web_server):
    # Create a temporary test image
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_img = f.name

    try:
        im = Image.new("RGBA", (200, 200), (255, 0, 0, 255))
        im.save(tmp_img)

        # 1. Normal thumbnail
        enc = urllib.parse.quote(tmp_img)
        url = f"{web_server.get_url()}/thumbnail?path={enc}&size=64"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") in ("image/jpeg", "image/png")
            data = resp.read()
            assert len(data) > 0

        # 2. Cropped thumbnail
        url_crop = f"{web_server.get_url()}/thumbnail?path={enc}&size=64&crop=10,10,100,100"
        with urllib.request.urlopen(urllib.request.Request(url_crop)) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") in ("image/jpeg", "image/png")
            data = resp.read()
            assert len(data) > 0

        # 3. Full-radius crop thumbnail has transparent corners
        url_circle = f"{web_server.get_url()}/thumbnail?path={enc}&size=64&radius=1"
        with urllib.request.urlopen(urllib.request.Request(url_circle)) as resp:
            assert resp.status == 200
            thumb = Image.open(io.BytesIO(resp.read())).convert("RGBA")
            assert thumb.getpixel((0, 0))[3] < 20
            assert thumb.getpixel((32, 32))[3] > 200
    finally:
        if os.path.exists(tmp_img):
            os.remove(tmp_img)


def test_thumbnail_bad_video_returns_placeholder(web_server):
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        tmp_file = f.name
        f.write(b"not a real video")

    try:
        enc = urllib.parse.quote(tmp_file)
        url = f"{web_server.get_url()}/thumbnail?path={enc}&size=64"
        with urllib.request.urlopen(urllib.request.Request(url)) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "image/png"
            data = resp.read()
            assert len(data) > 0
            Image.open(io.BytesIO(data)).convert("RGBA")
    finally:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)


def test_server_range_stream(web_server):
    # Create a dummy test file
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        tmp_file = f.name
        f.write(b"0" * 1024)

    try:
        enc = urllib.parse.quote(tmp_file)
        url = f"{web_server.get_url()}/stream?path={enc}"
        req = urllib.request.Request(url, headers={"Range": "bytes=0-99"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 206
            assert resp.headers.get("Content-Range") == "bytes 0-99/1024"
            data = resp.read()
            assert len(data) == 100
    finally:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)


def test_mkv_preview_stream_honors_seek_t(web_server, tmp_path):
    mkv_path = tmp_path / "seek.mkv"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=320x180:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-c:a", "aac",
        str(mkv_path),
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    enc = urllib.parse.quote(str(mkv_path))
    url = f"{web_server.get_url()}/stream?path={enc}&t=1.25"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=20) as resp:
        assert resp.status == 200
        assert "video/mp4" in (resp.headers.get("Content-Type") or "")
        data = resp.read(256 * 1024)
        assert b"ftyp" in data[:64]


def test_app_api_get_stream_url_includes_seek():
    api = AppAPI()
    url = api.get_stream_url(r"D:\media\clip.mkv", t=12.5)
    assert "path=" in url
    assert "t=12.500" in url


def test_proxy_status_is_opt_in(web_server, tmp_path):
    import json
    from core.proxy_manager import needs_proxy, reset_proxy_manager, set_proxy_cache_dir

    set_proxy_cache_dir(str(tmp_path / "proxies"))
    reset_proxy_manager()
    try:
        mkv_file = str(tmp_path / "optin.mkv")
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "testsrc=duration=1:size=320x180:rate=15",
                "-c:v", "libx264", "-preset", "ultrafast",
                mkv_file,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        assert needs_proxy(mkv_file)

        enc = urllib.parse.quote(mkv_file)
        url = f"{web_server.get_url()}/proxy_status?path={enc}&start=0"
        with urllib.request.urlopen(urllib.request.Request(url)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data["needs_proxy"] is True
        assert data["status"] == "not_started"

        start_url = f"{web_server.get_url()}/proxy_status?path={enc}&start=1"
        with urllib.request.urlopen(urllib.request.Request(start_url)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] in ("generating", "ready")

        from core.proxy_manager import get_proxy_manager
        pm = get_proxy_manager()
        status = None
        for _ in range(40):
            status = pm.get_proxy_status(mkv_file)
            if status.status in ("ready", "error"):
                break
            time.sleep(0.2)
        assert status.status == "ready", status.error

        stream_url = f"{web_server.get_url()}/stream?path={enc}"
        req = urllib.request.Request(stream_url, headers={"Range": "bytes=0-99"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 206
            assert len(resp.read()) == 100

        api = AppAPI()
        api_status = api.get_proxy_status(mkv_file, start=False)
        assert api_status["status"] == "ready"
        info = api.get_proxy_cache_info()
        assert info["count"] >= 1
        cleared = api.clear_proxy_cache()
        assert cleared["removed"] >= 1
    finally:
        reset_proxy_manager()
        set_proxy_cache_dir(None)


def test_app_api():
    api = AppAPI()
    info = api.get_info()
    assert "version" in info
    assert "stream_base_url" in info

    settings = api.get_settings()
    assert "preset_style" in settings

    # Test scan directory
    with tempfile.TemporaryDirectory() as tmpdir:
        f1 = os.path.join(tmpdir, "test1.mp4")
        f2 = os.path.join(tmpdir, "test2.png")
        f3 = os.path.join(tmpdir, "ignore.txt")
        open(f1, "wb").write(b"data")
        open(f2, "wb").write(b"data")
        open(f3, "wb").write(b"data")

        files = api.scan_directory(tmpdir)
        assert len(files) == 2
        assert f1 in files
        assert f2 in files
        assert f3 not in files

    # Test settings save and read sync
    with tempfile.TemporaryDirectory() as custom_dir:
        res = api.save_settings({"same_dir": False, "custom_output_dir": custom_dir})
        assert res.get("status") == "ok"
        updated = api.get_settings()
        assert updated["same_dir"] is False
        assert os.path.abspath(updated["custom_output_dir"]) == os.path.abspath(custom_dir)


def test_app_api_ai_workers(monkeypatch):
    api = AppAPI()
    js_calls = []
    logs = []
    monkeypatch.setattr(api, "_eval_js", lambda s: js_calls.append(s))
    monkeypatch.setattr(api, "_log", lambda m: logs.append(m))

    called_predict = []
    def mock_predict(path, config, max_retries=2, timeout=25, start_time=None, end_time=None):
        called_predict.append((path, start_time, end_time))
        return "🐱"

    monkeypatch.setattr("server.api.AIEmojiTagger.predict_emoji", mock_predict)

    # Test single worker
    api._run_ai_single_worker(1, "cat.png", start_time=0.5, end_time=2.5)
    assert len(called_predict) == 1
    assert called_predict[0] == ("cat.png", 0.5, 2.5)
    assert any("onAiItemFinished(1, \"🐱\")" in c for c in js_calls)

    # Test batch worker
    called_predict.clear()
    tasks = [
        {"task_id": 10, "input_path": "dog.png", "start_time": 0.0, "end_time": 1.0},
        {"task_id": 11, "input_path": "lol.mp4"},
    ]
    api._run_ai_worker(tasks)
    assert len(called_predict) == 2
    assert any("onAiItemFinished(10, \"🐱\")" in c for c in js_calls)
    assert any("onAiItemFinished(11, \"🐱\")" in c for c in js_calls)
    assert any("onAiAllCompleted()" in c for c in js_calls)


def test_conversion_runs_two_at_a_time(monkeypatch, tmp_path):
    api = AppAPI()
    monkeypatch.setattr(api, "_eval_js", lambda _s: None)
    monkeypatch.setattr(api, "_log", lambda _m: None)

    lock = threading.Lock()
    active = 0
    max_seen = 0

    def fake_convert(input_path, output_path, options=None, progress_callback=None):
        nonlocal active, max_seen
        with lock:
            active += 1
            max_seen = max(max_seen, active)
        time.sleep(0.25)
        with lock:
            active -= 1
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as fh:
            fh.write(b"webm")
        return True

    monkeypatch.setattr("server.api.StickerEncoder.convert", fake_convert)

    tasks = [
        {
            "task_id": i,
            "input_path": str(tmp_path / f"in{i}.mp4"),
            "output_path": str(tmp_path / "out" / f"{i}.webm"),
        }
        for i in range(4)
    ]
    api._run_conversion_worker(tasks, {"pack_output": False})
    assert max_seen == 2
    folders = [p for p in (tmp_path / "out").iterdir() if p.is_dir() and p.name.startswith("TG_Stickers_")]
    assert len(folders) == 1
    assert all((folders[0] / f"{i}.webm").is_file() for i in range(4))


