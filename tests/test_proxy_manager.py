import os
import subprocess
import time

from core.proc import ffmpeg_bin
from core.proxy_manager import (
    get_proxy_manager,
    needs_proxy,
    reset_proxy_manager,
    set_proxy_cache_dir,
)


def _make_mkv(path: str, seconds: float = 1.0) -> None:
    subprocess.run(
        [
            ffmpeg_bin(),
            "-y",
            "-f", "lavfi",
            "-i", f"testsrc=duration={seconds}:size=320x180:rate=15",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_needs_proxy_by_extension():
    assert needs_proxy(r"D:\a\clip.mkv") is True
    assert needs_proxy(r"D:\a\clip.avi") is True
    assert needs_proxy(r"D:\a\clip.mp4") is False
    assert needs_proxy(r"D:\a\clip.webm") is False


def test_proxy_status_not_started_until_requested(tmp_path):
    set_proxy_cache_dir(str(tmp_path / "proxies"))
    reset_proxy_manager()
    try:
        mkv = str(tmp_path / "src.mkv")
        _make_mkv(mkv)
        pm = get_proxy_manager()
        st = pm.get_proxy_status(mkv)
        assert st.status == "not_started"
        assert not pm.is_proxy_ready(mkv)
    finally:
        reset_proxy_manager()
        set_proxy_cache_dir(None)


def test_ensure_proxy_creates_seekable_mp4(tmp_path):
    set_proxy_cache_dir(str(tmp_path / "proxies"))
    reset_proxy_manager()
    try:
        mkv = str(tmp_path / "src.mkv")
        _make_mkv(mkv)
        pm = get_proxy_manager()
        pm.ensure_proxy_async(mkv)
        status = None
        for _ in range(40):
            status = pm.get_proxy_status(mkv)
            if status.status in ("ready", "error"):
                break
            time.sleep(0.2)
        assert status is not None
        assert status.status == "ready", status.error
        assert status.proxy_path and os.path.isfile(status.proxy_path)
        assert os.path.getsize(status.proxy_path) > 1024

        info = pm.cache_info()
        assert info["count"] >= 1
        cleared = pm.clear_cache()
        assert cleared["removed"] >= 1
        assert not os.path.isfile(status.proxy_path)
    finally:
        reset_proxy_manager()
        set_proxy_cache_dir(None)


def test_install_proxy_file_keys_to_new_path(tmp_path):
    set_proxy_cache_dir(str(tmp_path / "cache"))
    reset_proxy_manager()
    try:
        src = tmp_path / "a.mkv"
        imported = tmp_path / "b.mkv"
        src.write_bytes(b"a" * 2000)
        imported.write_bytes(b"a" * 2000)
        blob = tmp_path / "exported.mp4"
        blob.write_bytes(b"P" * 2048)
        pm = get_proxy_manager()
        assert pm.install_proxy_file(str(imported), str(blob))
        assert pm.is_proxy_ready(str(imported))
        assert not pm.is_proxy_ready(str(src))
    finally:
        reset_proxy_manager()
        set_proxy_cache_dir(None)


def test_proxy_path_casing_normalization(tmp_path):
    set_proxy_cache_dir(str(tmp_path / "proxies"))
    reset_proxy_manager()
    try:
        mkv = str(tmp_path / "src.mkv")
        _make_mkv(mkv)
        pm = get_proxy_manager()
        pm.ensure_proxy_async(mkv.upper() if os.name == "nt" else mkv)
        query_path = mkv.lower() if os.name == "nt" else mkv
        st = pm.get_proxy_status(query_path)
        assert st.status in ("generating", "ready")
    finally:
        reset_proxy_manager()
        set_proxy_cache_dir(None)

