import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse
from PIL import Image, ImageOps

from core.crop_shape import apply_crop_radius, normalize_crop_radius, radius_needs_alpha
from core.proc import ffmpeg_bin, popen_hidden, run_hidden
from core.proxy_manager import get_proxy_manager, needs_proxy

_THUMB_FFMPEG_SEMA = threading.Semaphore(2)
_THUMB_CACHE_LOCK = threading.Lock()
_THUMB_CACHE: dict[tuple, tuple[float, bytes]] = {}
_THUMB_CACHE_MAX = 80
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".m4v", ".ts", ".m2ts"}
_DIST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))


def _ffmpeg_path() -> str:
    try:
        return ffmpeg_bin()
    except FileNotFoundError:
        return "ffmpeg"


def _is_within(root: str, path: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(root), os.path.abspath(path)]) == os.path.abspath(root)
    except ValueError:
        return False

# 客户端拖动进度、取消请求或关闭页面时，Windows 会抛 ConnectionAbortedError
_CLIENT_GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, ConnectionRefusedError)


class LocalStreamHandler(BaseHTTPRequestHandler):
    """
    HTTP handler providing:
    1. HTTP 206 Range streaming for local MP4/WebM files (instant scrub & seek).
    2. Real-time FFmpeg remuxing/preview streaming for MKV and other formats.
    3. Dynamic thumbnail generation with crop support.
    """

    server_version = "StickerMakerStream/1.0"

    def log_message(self, format, *args):
        # Suppress noisy HTTP request logs
        pass

    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type, Accept")
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges")

    def _write_body(self, data: bytes) -> bool:
        try:
            self.wfile.write(data)
            return True
        except _CLIENT_GONE:
            return False

    def _copyfile(self, src) -> None:
        try:
            shutil.copyfileobj(src, self.wfile, length=64 * 1024)
        except _CLIENT_GONE:
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/health":
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self._write_body(b'{"status":"ok"}')
            return

        elif path == "/stream":
            self._handle_stream(params)
            return

        elif path == "/proxy_status":
            self._handle_proxy_status(params)
            return

        elif path == "/thumbnail":
            self._handle_thumbnail(params)
            return

        if os.path.isdir(_DIST_DIR):
            import mimetypes
            req_rel = path.lstrip("/")
            if not req_rel:
                req_rel = "index.html"
            target_file = os.path.abspath(os.path.join(_DIST_DIR, req_rel))
            if not os.path.isfile(target_file):
                target_file = os.path.join(_DIST_DIR, "index.html")
            if _is_within(_DIST_DIR, target_file) and os.path.isfile(target_file):
                ctype, _ = mimetypes.guess_type(target_file)
                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", ctype or "application/octet-stream")
                sz = os.path.getsize(target_file)
                self.send_header("Content-Length", str(sz))
                self.end_headers()
                with open(target_file, "rb") as f:
                    self._copyfile(f)
                return

        self.send_error(404, "Endpoint not found")

    def _serve_file_range(self, file_path: str, mime: str = "video/mp4") -> None:
        file_size = os.path.getsize(file_path)
        range_header = self.headers.get("Range")

        if range_header:
            match = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if match:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else file_size - 1
                end = min(end, file_size - 1)
                length = end - start + 1

                self.send_response(206)
                self._set_cors_headers()
                self.send_header("Content-Type", mime)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    chunk_size = 64 * 1024
                    while remaining > 0:
                        read_bytes = min(remaining, chunk_size)
                        data = f.read(read_bytes)
                        if not data:
                            break
                        if not self._write_body(data):
                            break
                        remaining -= len(data)
                return

        self.send_response(200)
        self._set_cors_headers()
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(file_path, "rb") as f:
            self._copyfile(f)

    def _resolve_path(self, raw_path: str) -> str:
        if not raw_path:
            return ""
        if os.path.isfile(raw_path):
            return os.path.abspath(raw_path)
        unquoted = unquote(raw_path)
        if os.path.isfile(unquoted):
            return os.path.abspath(unquoted)
        return os.path.abspath(raw_path)

    def _handle_proxy_status(self, params):
        raw_path = params.get("path", [""])[0]
        file_path = self._resolve_path(raw_path)
        if not file_path or not os.path.isfile(file_path):
            self.send_error(404, f"File not found: {file_path}")
            return

        start = params.get("start", ["0"])[0] in ("1", "true", "yes")
        pm = get_proxy_manager()
        is_needed = needs_proxy(file_path)
        if is_needed and start:
            pm.ensure_proxy_async(file_path)
        task = pm.get_proxy_status(file_path)

        self.send_response(200)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        payload = json.dumps({
            "status": task.status,
            "progress": round(task.progress, 3),
            "error": task.error,
            "needs_proxy": is_needed,
        })
        self._write_body(payload.encode("utf-8"))

    def _handle_stream(self, params):
        raw_path = params.get("path", [""])[0]
        file_path = self._resolve_path(raw_path)

        if not file_path or not os.path.isfile(file_path):
            self.send_error(404, f"File not found: {file_path}")
            return

        ext = os.path.splitext(file_path)[1].lower()

        if not needs_proxy(file_path):
            mime = "video/mp4" if ext == ".mp4" else ("video/webm" if ext == ".webm" else "video/ogg")
            self._serve_file_range(file_path, mime)
            return

        force_live = params.get("live", ["0"])[0].lower() in ("1", "true", "yes")
        if not force_live:
            pm = get_proxy_manager()
            task = pm.get_proxy_status(file_path)
            if task.status == "ready" and task.proxy_path and os.path.isfile(task.proxy_path):
                self._serve_file_range(task.proxy_path, "video/mp4")
                return

        # For MKV and other formats: on-the-fly preview remux / transcode to fragmented MP4.
        # This pipe is not HTTP-Range seekable; the client must pass t= to restart FFmpeg.
        try:
            seek_sec = float(params.get("t", ["0"])[0])
        except (TypeError, ValueError):
            seek_sec = 0.0
        seek_sec = max(0.0, seek_sec)
        self.send_response(200)
        self._set_cors_headers()
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        # Fast preview transcode / remux
        cmd = [
            _ffmpeg_path(),
            "-hide_banner",
            "-loglevel", "error",
            "-ss", f"{seek_sec:.3f}",
            "-i", file_path,
            "-map", "0:v:0",
            "-map", "0:a:0?",
            "-sn",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-vf", "scale=-2:480",
            "-c:a", "aac",
            "-b:a", "96k",
            "-avoid_negative_ts", "make_zero",
            "-f", "mp4",
            "-movflags", "frag_keyframe+empty_moov+default_base_moof",
            "pipe:1",
        ]
        proc = popen_hidden(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while True:
                chunk = proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                if not self._write_body(chunk):
                    break
        except _CLIENT_GONE:
            pass
        finally:
            proc.kill()

    def _handle_thumbnail(self, params):
        raw_path = params.get("path", [""])[0]
        file_path = self._resolve_path(raw_path)
        if not file_path or not os.path.isfile(file_path):
            self.send_error(404, "File not found")
            return

        try:
            ts = float(params.get("t", ["0.0"])[0])
        except (TypeError, ValueError):
            ts = 0.0
        try:
            size = max(16, min(int(params.get("size", ["80"])[0]), 1280))
        except (TypeError, ValueError):
            size = 80
        crop_str = params.get("crop", [""])[0]  # "x,y,w,h"
        crop = None
        if crop_str:
            try:
                parts = [int(p) for p in crop_str.split(",")]
                if len(parts) == 4:
                    crop = tuple(parts)
            except (TypeError, ValueError):
                pass
        radius = normalize_crop_radius(params.get("radius", [""])[0])
        mirror_param = params.get("mirror", ["0"])[0].strip().lower()
        mirror = mirror_param in ("1", "true", "yes")

        try:
            mtime = os.path.getmtime(file_path)
        except OSError:
            mtime = 0.0
        cache_key = (file_path, round(ts, 3), size, crop, round(radius, 3), mirror)
        cached = _thumb_cache_get(cache_key, mtime)
        if cached is not None:
            self._send_png(cached)
            return

        ext = os.path.splitext(file_path)[1].lower()
        is_video = ext in _VIDEO_EXTS

        pil_img = None
        if is_video:
            pil_img = _grab_video_frame(file_path, ts, size, crop, mirror)
            crop = None
        else:
            try:
                with Image.open(file_path) as im:
                    pil_img = im.convert("RGBA")
                    if mirror:
                        pil_img = ImageOps.mirror(pil_img)
            except (OSError, ValueError):
                pass

        if pil_img is None:
            pil_img = Image.new("RGBA", (size, size), (30, 35, 45, 255))

        if crop is not None:
            cx, cy, cw, ch = crop
            w, h = pil_img.size
            x0 = max(0, min(cx, w - 1))
            y0 = max(0, min(cy, h - 1))
            x1 = max(x0 + 1, min(cx + cw, w))
            y1 = max(y0 + 1, min(cy + ch, h))
            if x1 > x0 and y1 > y0:
                pil_img = pil_img.crop((x0, y0, x1, y1))

        pil_img.thumbnail((size, size), Image.Resampling.LANCZOS)
        if radius_needs_alpha(radius):
            pil_img = apply_crop_radius(pil_img, radius)
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        _thumb_cache_put(cache_key, mtime, png_bytes)
        self._send_png(png_bytes)

    def _send_png(self, png_bytes: bytes) -> None:
        self.send_response(200)
        self._set_cors_headers()
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(png_bytes)))
        self.send_header("Cache-Control", "public, max-age=60")
        self.end_headers()
        self._write_body(png_bytes)


def _thumb_cache_get(key: tuple, mtime: float) -> bytes | None:
    with _THUMB_CACHE_LOCK:
        item = _THUMB_CACHE.get(key)
        if item and item[0] == mtime:
            return item[1]
        return None


def _thumb_cache_put(key: tuple, mtime: float, data: bytes) -> None:
    with _THUMB_CACHE_LOCK:
        if len(_THUMB_CACHE) >= _THUMB_CACHE_MAX:
            _THUMB_CACHE.pop(next(iter(_THUMB_CACHE)))
        _THUMB_CACHE[key] = (mtime, data)


def _grab_video_frame(
    file_path: str,
    ts: float,
    size: int,
    crop: tuple[int, int, int, int] | None,
    mirror: bool = False,
) -> Image.Image | None:
    """Decode one frame, crop/scale inside ffmpeg. Never raises."""
    filters = []
    if mirror:
        filters.append("hflip")
    if crop is not None:
        cx, cy, cw, ch = crop
        cw = max(2, cw)
        ch = max(2, ch)
        cx = max(0, cx)
        cy = max(0, cy)
        filters.append(f"crop={cw}:{ch}:{cx}:{cy}")
    filters.append(
        f"scale={size}:{size}:force_original_aspect_ratio=decrease:flags=fast_bilinear"
    )
    cmd = [
        _ffmpeg_path(),
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
        "-an",
        "-sn",
        "-ss", f"{max(0.0, ts):.3f}",
        "-i", file_path,
        "-frames:v", "1",
        "-vf", ",".join(filters),
        "-f", "image2pipe",
        "-vcodec", "png",
        "-",
    ]
    acquired = _THUMB_FFMPEG_SEMA.acquire(timeout=20)
    if not acquired:
        return None
    try:
        res = run_hidden(
            cmd,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=12,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    finally:
        _THUMB_FFMPEG_SEMA.release()

    if res.returncode != 0 or not res.stdout:
        return None
    try:
        with Image.open(io.BytesIO(res.stdout)) as im:
            return im.convert("RGBA")
    except (OSError, ValueError):
        return None


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        err = sys.exception()
        if isinstance(err, (*_CLIENT_GONE, subprocess.TimeoutExpired)):
            return
        super().handle_error(request, client_address)


class LocalStreamServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.server = _QuietThreadingHTTPServer((host, port), LocalStreamHandler)
        self.port = self.server.server_address[1]
        self.host = host
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def get_url(self, endpoint: str = "") -> str:
        return f"http://{self.host}:{self.port}{endpoint}"


_global_stream_server = None


def start_stream_server(host: str = "127.0.0.1", port: int = 0) -> LocalStreamServer:
    global _global_stream_server
    if _global_stream_server is None:
        _global_stream_server = LocalStreamServer(host=host, port=port)
        _global_stream_server.start()
    return _global_stream_server


def get_stream_server() -> LocalStreamServer:
    global _global_stream_server
    if _global_stream_server is None:
        return start_stream_server()
    return _global_stream_server
