"""Lightweight H.264 MP4 preview proxies for formats the browser cannot Range-seek."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from core.analyzer import MediaAnalyzer
from core.proc import ffmpeg_bin, popen_hidden, run_hidden

_RANGE_STREAM_EXTS = {".mp4", ".webm", ".ogg"}
_PROXY_CACHE_DIR: Optional[str] = None
_BEST_ENCODER_INFO: Optional[Tuple[str, List[str]]] = None
_ENCODER_DETECT_LOCK = threading.Lock()


def get_proxy_cache_dir() -> str:
    if _PROXY_CACHE_DIR is not None:
        return _PROXY_CACHE_DIR
    from core.app_paths import proxy_dir

    target = proxy_dir()
    os.makedirs(target, exist_ok=True)
    return target


def set_proxy_cache_dir(path: Optional[str]) -> None:
    """Test helper: override cache directory. Pass None to restore default."""
    global _PROXY_CACHE_DIR
    if path:
        os.makedirs(path, exist_ok=True)
        _PROXY_CACHE_DIR = path
    else:
        _PROXY_CACHE_DIR = None


def canonical_media_path(file_path: str) -> str:
    return os.path.normcase(os.path.abspath(file_path))


def needs_proxy(file_path: str) -> bool:
    ext = os.path.splitext(file_path)[1].lower()
    return ext not in _RANGE_STREAM_EXTS


def compute_file_cache_key(file_path: str) -> str:
    abs_path = canonical_media_path(file_path)
    try:
        mtime = os.path.getmtime(abs_path)
        size = os.path.getsize(abs_path)
    except OSError:
        mtime = 0.0
        size = 0
    raw = f"{abs_path}|{mtime}|{size}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def detect_best_h264_encoder() -> Tuple[str, List[str]]:
    global _BEST_ENCODER_INFO
    with _ENCODER_DETECT_LOCK:
        if _BEST_ENCODER_INFO is not None:
            return _BEST_ENCODER_INFO

        ffmpeg = ffmpeg_bin()
        candidates = [
            ("h264_nvenc", ["-preset", "p1", "-cq", "28"]),
            ("h264_qsv", ["-preset", "veryfast", "-global_quality", "28"]),
            ("h264_amf", ["-quality", "speed", "-rc", "cqp", "-qp_p", "28"]),
        ]
        for enc, extra in candidates:
            try:
                res = run_hidden(
                    [
                        ffmpeg,
                        "-hide_banner",
                        "-loglevel", "error",
                        "-f", "lavfi",
                        "-i", "color=c=black:s=256x256:r=25",
                        "-frames:v", "10",
                        "-c:v", enc,
                        *extra,
                        "-f", "null",
                        "-",
                    ],
                    timeout=4,
                )
                if res.returncode == 0:
                    _BEST_ENCODER_INFO = (enc, extra)
                    return _BEST_ENCODER_INFO
            except (OSError, subprocess.TimeoutExpired):
                pass

        _BEST_ENCODER_INFO = (
            "libx264",
            ["-preset", "ultrafast", "-crf", "28", "-tune", "fastdecode"],
        )
        return _BEST_ENCODER_INFO


@dataclass
class ProxyTask:
    status: str  # "not_needed" | "ready" | "generating" | "error" | "not_started"
    progress: float  # 0.0 to 1.0
    proxy_path: Optional[str] = None
    error: Optional[str] = None


class ProxyManager:
    """Generate and cache a seekable 480p H.264 MP4 for MKV/AVI/etc. preview."""

    MAX_CACHED_PROXIES = 60

    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: Dict[str, ProxyTask] = {}
        self._procs: Dict[str, subprocess.Popen] = {}

    def get_proxy_path(self, file_path: str) -> str:
        key = compute_file_cache_key(file_path)
        return os.path.join(get_proxy_cache_dir(), f"proxy_{key}.mp4")

    def is_proxy_ready(self, file_path: str) -> bool:
        if not needs_proxy(file_path):
            return True
        proxy_path = self.get_proxy_path(file_path)
        return os.path.isfile(proxy_path) and os.path.getsize(proxy_path) > 1024

    def get_proxy_status(self, file_path: str) -> ProxyTask:
        if not needs_proxy(file_path):
            return ProxyTask(status="not_needed", progress=1.0, proxy_path=file_path)

        proxy_path = self.get_proxy_path(file_path)
        if os.path.isfile(proxy_path) and os.path.getsize(proxy_path) > 1024:
            return ProxyTask(status="ready", progress=1.0, proxy_path=proxy_path)

        key = canonical_media_path(file_path)
        with self._lock:
            task = self._tasks.get(key)
            if task is not None:
                return ProxyTask(
                    status=task.status,
                    progress=task.progress,
                    proxy_path=task.proxy_path,
                    error=task.error,
                )
        return ProxyTask(status="not_started", progress=0.0)

    def ensure_proxy_async(self, file_path: str) -> ProxyTask:
        if not needs_proxy(file_path):
            return ProxyTask(status="not_needed", progress=1.0, proxy_path=file_path)

        proxy_path = self.get_proxy_path(file_path)
        if os.path.isfile(proxy_path) and os.path.getsize(proxy_path) > 1024:
            return ProxyTask(status="ready", progress=1.0, proxy_path=proxy_path)

        key = canonical_media_path(file_path)
        with self._lock:
            existing = self._tasks.get(key)
            if existing and existing.status == "generating":
                return existing
            task = ProxyTask(status="generating", progress=0.0)
            self._tasks[key] = task

        thread = threading.Thread(
            target=self._generate_worker,
            args=(os.path.abspath(file_path), proxy_path, task),
            daemon=True,
        )
        thread.start()
        return task

    def ready_proxy_path(self, file_path: str) -> Optional[str]:
        """Return the cached proxy file if it is ready to copy into a bundle."""
        if not needs_proxy(file_path):
            return None
        st = self.get_proxy_status(file_path)
        if st.status != "ready" or not st.proxy_path:
            return None
        if os.path.isfile(st.proxy_path) and os.path.getsize(st.proxy_path) > 1024:
            return st.proxy_path
        return None

    def install_proxy_file(self, file_path: str, proxy_src: str) -> bool:
        """Copy an exported proxy into the cache slot for ``file_path``."""
        if not needs_proxy(file_path):
            return False
        if not os.path.isfile(proxy_src) or os.path.getsize(proxy_src) <= 1024:
            return False
        dest = self.get_proxy_path(file_path)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        src_abs = os.path.abspath(proxy_src)
        dest_abs = os.path.abspath(dest)
        if src_abs != dest_abs:
            shutil.copy2(src_abs, dest_abs)
            os.utime(dest_abs, None)
        if not os.path.isfile(dest_abs) or os.path.getsize(dest_abs) <= 1024:
            return False
        key = canonical_media_path(file_path)
        with self._lock:
            self._tasks[key] = ProxyTask(
                status="ready",
                progress=1.0,
                proxy_path=dest_abs,
            )
        self._cleanup_old_proxies()
        return True

    def cache_info(self) -> dict:
        cache_dir = get_proxy_cache_dir()
        files = []
        try:
            files = [
                os.path.join(cache_dir, f)
                for f in os.listdir(cache_dir)
                if f.startswith("proxy_") and f.endswith(".mp4")
            ]
        except OSError:
            files = []
        total = 0
        for p in files:
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
        return {
            "dir": cache_dir,
            "count": len(files),
            "bytes": total,
        }

    def clear_cache(self) -> dict:
        info = self.cache_info()
        removed = 0
        cache_dir = get_proxy_cache_dir()
        try:
            names = os.listdir(cache_dir)
        except OSError:
            names = []
        for name in names:
            if not (name.startswith("proxy_") and (name.endswith(".mp4") or ".tmp." in name)):
                continue
            path = os.path.join(cache_dir, name)
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
        with self._lock:
            self._tasks.clear()
        return {"removed": removed, "dir": cache_dir, "had_bytes": info["bytes"]}

    def _generate_worker(self, file_path: str, proxy_path: str, task: ProxyTask) -> None:
        tmp_path = f"{proxy_path}.{os.getpid()}_{threading.get_ident()}.tmp.mp4"
        try:
            self._cleanup_old_proxies()
            media_info = MediaAnalyzer.analyze(file_path)
            duration = max(0.1, media_info.duration)
            codec = (media_info.video_codec or "").lower()
            can_remux = codec in ("h264", "avc1", "avc")

            ffmpeg = ffmpeg_bin()
            if can_remux:
                cmd = [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel", "error",
                    "-nostdin",
                    "-stats_period", "0.1",
                    "-i", file_path,
                    "-map", "0:v:0",
                    "-map", "0:a:0?",
                    "-sn",
                    "-dn",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-ac", "2",
                    "-f", "mp4",
                    "-movflags", "+faststart",
                    "-progress", "pipe:1",
                    tmp_path,
                ]
                success = self._run_ffmpeg_with_progress(file_path, cmd, duration, task)
                if success and os.path.isfile(tmp_path) and os.path.getsize(tmp_path) > 1024:
                    os.replace(tmp_path, proxy_path)
                    task.status = "ready"
                    task.progress = 1.0
                    task.proxy_path = proxy_path
                    return
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

            enc, enc_args = detect_best_h264_encoder()
            cmd = self._build_transcode_cmd(file_path, tmp_path, enc, enc_args)
            success = self._run_ffmpeg_with_progress(file_path, cmd, duration, task)

            if not success and enc != "libx264":
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                fallback_cmd = self._build_transcode_cmd(
                    file_path,
                    tmp_path,
                    "libx264",
                    ["-preset", "ultrafast", "-crf", "28", "-tune", "fastdecode"],
                )
                success = self._run_ffmpeg_with_progress(file_path, fallback_cmd, duration, task)

            if success and os.path.isfile(tmp_path) and os.path.getsize(tmp_path) > 1024:
                os.replace(tmp_path, proxy_path)
                task.status = "ready"
                task.progress = 1.0
                task.proxy_path = proxy_path
            else:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                task.status = "error"
                task.error = task.error or "FFmpeg proxy generation failed"
        except Exception as e:
            task.status = "error"
            task.error = str(e)
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        finally:
            with self._lock:
                self._procs.pop(canonical_media_path(file_path), None)

    def _build_transcode_cmd(
        self,
        file_path: str,
        output_path: str,
        enc: str,
        enc_args: List[str],
    ) -> List[str]:
        ffmpeg = ffmpeg_bin()
        hw = ["-hwaccel", "auto"] if enc != "libx264" else []
        return [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
            "-stats_period", "0.1",
            *hw,
            "-i", file_path,
            "-map", "0:v:0",
            "-map", "0:a:0?",
            "-sn",
            "-dn",
            "-c:v", enc,
            *enc_args,
            "-pix_fmt", "yuv420p",
            "-vf", "scale=-2:480:flags=fast_bilinear",
            "-c:a", "aac",
            "-b:a", "96k",
            "-ac", "2",
            "-f", "mp4",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            output_path,
        ]

    def _run_ffmpeg_with_progress(
        self,
        file_path: str,
        cmd: List[str],
        duration: float,
        task: ProxyTask,
    ) -> bool:
        proc = popen_hidden(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with self._lock:
            self._procs[canonical_media_path(file_path)] = proc

        err_output: List[str] = []

        def read_stderr():
            try:
                for line in iter(proc.stderr.readline, b""):
                    err_output.append(line.decode("utf-8", errors="ignore"))
            except Exception:
                pass

        t_err = threading.Thread(target=read_stderr, daemon=True)
        t_err.start()

        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="ignore").strip()
                if decoded.startswith("out_time_us="):
                    try:
                        us = int(decoded.split("=")[1])
                        sec = us / 1_000_000.0
                        task.progress = min(0.99, max(0.0, sec / duration))
                    except (ValueError, IndexError):
                        pass
                elif decoded.startswith("out_time_ms="):
                    try:
                        ms = int(decoded.split("=")[1])
                        sec = ms / 1_000.0
                        task.progress = min(0.99, max(0.0, sec / duration))
                    except (ValueError, IndexError):
                        pass
                elif decoded == "progress=end":
                    task.progress = 0.99
            proc.wait()
            t_err.join(timeout=1.0)
            if proc.returncode != 0:
                task.error = "".join(err_output).strip() or f"FFmpeg exited with code {proc.returncode}"
            return proc.returncode == 0
        except Exception as e:
            task.error = str(e)
            try:
                proc.kill()
            except OSError:
                pass
            return False

    def _cleanup_old_proxies(self) -> None:
        try:
            cache_dir = get_proxy_cache_dir()
            files = [
                os.path.join(cache_dir, f)
                for f in os.listdir(cache_dir)
                if f.startswith("proxy_") and f.endswith(".mp4")
            ]
            if len(files) <= self.MAX_CACHED_PROXIES:
                return
            files.sort(key=lambda p: os.path.getmtime(p))
            for p in files[: len(files) - self.MAX_CACHED_PROXIES]:
                try:
                    os.remove(p)
                except OSError:
                    pass
        except OSError:
            pass


_GLOBAL_PROXY_MANAGER: Optional[ProxyManager] = None


def get_proxy_manager() -> ProxyManager:
    global _GLOBAL_PROXY_MANAGER
    if _GLOBAL_PROXY_MANAGER is None:
        _GLOBAL_PROXY_MANAGER = ProxyManager()
    return _GLOBAL_PROXY_MANAGER


def reset_proxy_manager() -> None:
    global _GLOBAL_PROXY_MANAGER
    _GLOBAL_PROXY_MANAGER = None
