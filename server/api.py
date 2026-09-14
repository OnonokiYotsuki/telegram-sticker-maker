import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Dict, List, Optional
import urllib.parse

import webview

from core import __version__
from core.ai_tagger import AIEmojiConfig, AIEmojiTagger
from core.analyzer import MediaAnalyzer
from core.encoder import EncodeOptions, StickerEncoder
from core.settings_store import default_settings
from core.settings_store import load_settings as load_app_settings
from core.settings_store import save_settings as save_app_settings
from server.stream_server import get_stream_server

try:
    from webview.dom import _dnd_state
    _dnd_state["num_listeners"] = 999
except Exception:
    _dnd_state = {"num_listeners": 999, "paths": []}


def _file_dialog_type(kind: str):
    file_dialog = getattr(webview, "FileDialog", None)
    if file_dialog is not None:
        return getattr(file_dialog, kind)
    legacy = {"OPEN": "OPEN_DIALOG", "FOLDER": "FOLDER_DIALOG", "SAVE": "SAVE_DIALOG"}
    return getattr(webview, legacy[kind])



class AppAPI:
    """
    Python API exposed to Frontend via window.pywebview.api.
    All methods return JSON-serializable structures.
    """

    CONVERT_WORKERS = 2

    def __init__(self):
        self._canceled = False
        self._js_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=self.CONVERT_WORKERS)
        self.stream_server = get_stream_server()

    def _eval_js(self, js_code: str):
        if not webview.windows:
            return
        try:
            with self._js_lock:
                webview.windows[0].evaluate_js(js_code)
        except Exception:
            pass

    def _emit(self, name: str, *args: Any) -> None:
        if not name.isidentifier():
            return
        payload = ", ".join(json.dumps(a, ensure_ascii=False) for a in args)
        self._eval_js(f"if (window.{name}) window.{name}({payload});")

    def get_info(self) -> Dict[str, Any]:
        return {
            "version": __version__,
            "stream_base_url": self.stream_server.get_url(),
            "os": "windows" if os.name == "nt" else "unix",
        }

    def get_dropped_files(self) -> List[str]:
        paths = [p[1] for p in _dnd_state.get("paths", [])]
        _dnd_state["paths"].clear()
        return paths

    def scan_directory(self, folder_path: str) -> List[str]:
        if not folder_path or not os.path.isdir(folder_path):
            return []
        media_files = []
        for root, _, files in os.walk(folder_path):
            for f in sorted(files):
                ext = os.path.splitext(f)[1].lower()
                if ext in MediaAnalyzer.MEDIA_EXTENSIONS:
                    media_files.append(os.path.join(root, f))
        return media_files

    def select_files(self) -> List[str]:
        if not webview.windows:
            return []
        file_types = ("Supported Media (*.mp4;*.mkv;*.webm;*.mov;*.avi;*.flv;*.png;*.jpg;*.jpeg;*.webp;*.gif;*.apng;*.heic;*.heif)", "All Files (*.*)")
        result = webview.windows[0].create_file_dialog(
            _file_dialog_type("OPEN"),
            allow_multiple=True,
            file_types=file_types,
        )
        if not result:
            return []
        return list(result)

    def select_directory(self) -> str:
        if not webview.windows:
            return ""
        result = webview.windows[0].create_file_dialog(_file_dialog_type("FOLDER"))
        if not result:
            return ""
        return result[0] if isinstance(result, (list, tuple)) else str(result)

    def open_folder(self, folder_path: str):
        if not folder_path:
            return
        abs_path = os.path.abspath(folder_path)
        if os.path.isfile(abs_path):
            abs_path = os.path.dirname(abs_path)
        if not os.path.exists(abs_path):
            try:
                os.makedirs(abs_path, exist_ok=True)
            except Exception:
                pass
        if os.path.exists(abs_path):
            if os.name == "nt":
                os.startfile(abs_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", abs_path], check=False)
            else:
                subprocess.run(["xdg-open", abs_path], check=False)

    def analyze_file(self, file_path: str) -> Dict[str, Any]:
        if not os.path.isfile(file_path):
            return {"error": "File does not exist"}
        try:
            info = MediaAnalyzer.analyze(file_path)
            return info.to_dict()
        except Exception as e:
            return {"error": str(e)}

    def get_stream_url(self, file_path: str, t: float = 0.0) -> str:
        encoded = urllib.parse.quote(file_path)
        return self.stream_server.get_url(f"/stream?path={encoded}&t={t:.3f}")

    def get_thumbnail_url(
        self,
        file_path: str,
        t: float = 0.0,
        crop: Optional[str] = None,
        size: int = 80,
        radius: Optional[float] = None,
    ) -> str:
        encoded = urllib.parse.quote(file_path)
        url = f"/thumbnail?path={encoded}&t={t:.3f}&size={size}"
        if crop:
            url += f"&crop={crop}"
        if radius:
            url += f"&radius={radius}"
        return self.stream_server.get_url(url)

    def get_settings(self) -> Dict[str, Any]:
        try:
            return load_app_settings()
        except (OSError, ValueError):
            return default_settings()

    def ai_tag_single(
        self,
        task_id: int,
        input_path: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ):
        threading.Thread(
            target=self._run_ai_single_worker,
            args=(task_id, input_path, start_time, end_time),
            daemon=True,
        ).start()
        return {"status": "started"}

    def _run_ai_single_worker(
        self,
        task_id: int,
        in_path: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ):
        config = AIEmojiConfig.load()
        fname = os.path.basename(in_path)
        self._emit("onAiItemStarted", task_id, fname)
        try:
            emoji = AIEmojiTagger.predict_emoji(
                in_path, config, start_time=start_time, end_time=end_time
            )
            self._log(f"[AI Emoji] {fname} -> {emoji or '无匹配'}")
            self._emit("onAiItemFinished", task_id, emoji)
        except Exception as e:
            self._log(f"[AI 提示] {fname}: {e}")
            self._emit("onAiItemError", task_id, str(e))

    def save_settings(self, data: Dict[str, Any]):
        try:
            save_app_settings(data)
            return {"status": "ok"}
        except Exception as e:
            return {"error": str(e)}

    def cancel_conversion(self):
        self._canceled = True
        self._log(">>> 用户请求取消转换。")

    def start_conversion(self, tasks: List[Dict[str, Any]], global_options: Dict[str, Any]):
        self._canceled = False
        threading.Thread(target=self._run_conversion_worker, args=(tasks, global_options), daemon=True).start()
        return {"status": "started"}

    def _log(self, message: str):
        self._emit("onLog", message)

    def _run_conversion_worker(self, tasks: List[Dict[str, Any]], global_options: Dict[str, Any]):
        self._log(f">>> 开始执行 {len(tasks)} 个转换任务（最多 {self.CONVERT_WORKERS} 路并行）...")
        futures = [
            self._executor.submit(self._convert_one, task, global_options)
            for task in tasks
        ]
        wait(futures)
        for fut in futures:
            exc = fut.exception()
            if exc is not None:
                self._log(f"❌ 转换线程异常: {exc}")
        if self._canceled:
            self._log(">>> 批量转换已取消。")
        self._log(">>> 所有转换任务已结束。")
        self._emit("onAllCompleted")

    def _convert_one(self, task: Dict[str, Any], global_options: Dict[str, Any]) -> None:
        task_id = task.get("task_id", 0)
        in_path = task.get("input_path", "")
        out_path = task.get("output_path", "")

        if self._canceled:
            self._emit("onTaskFinished", task_id, False, "已取消", "", 0)
            return

        preset_style = global_options.get("preset_style", "anime")
        spoof_duration = global_options.get("spoof_duration", True)
        optimize_fps = global_options.get("optimize_fps", True)
        is_custom_emoji = global_options.get("is_custom_emoji", False)
        start_t = task.get("start_time")
        end_t = task.get("end_time")
        crop = task.get("crop")
        if crop and isinstance(crop, list) and len(crop) == 4:
            crop = tuple(crop)
        crop_radius = task.get("crop_radius") or 0.0

        opts = EncodeOptions(
            preset_style=preset_style,
            spoof_duration=spoof_duration,
            optimize_fps=optimize_fps,
            is_custom_emoji=is_custom_emoji,
            start_time=start_t,
            end_time=end_t,
            crop=crop,
            crop_radius=crop_radius,
        )

        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        self._log(f"[{os.path.basename(in_path)}] 开始转码...")
        self._emit("onTaskStarted", task_id)

        def on_progress(p: float, msg: str):
            if self._canceled:
                raise InterruptedError("User cancelled")
            self._emit("onTaskProgress", task_id, p, msg)
            if int(p * 100) % 25 == 0:
                self._log(f"[{os.path.basename(in_path)}] {msg}")

        try:
            success = StickerEncoder.convert(
                input_path=in_path,
                output_path=out_path,
                options=opts,
                progress_callback=on_progress,
            )
            if success and os.path.exists(out_path):
                sz = os.path.getsize(out_path)
                msg = "转换成功"
                self._log(f"✅ [{os.path.basename(in_path)}] 转换成功 ({sz/1024:.1f} KB)")
                self._emit("onTaskFinished", task_id, True, msg, out_path, sz)
            else:
                msg = "转码未生成有效文件"
                self._log(f"❌ [{os.path.basename(in_path)}] 失败: {msg}")
                self._emit("onTaskFinished", task_id, False, msg, "", 0)
        except InterruptedError:
            self._log(f"[{os.path.basename(in_path)}] 任务已取消。")
            self._emit("onTaskFinished", task_id, False, "已取消", "", 0)
        except Exception as e:
            self._log(f"❌ [{os.path.basename(in_path)}] 报错: {str(e)}")
            self._emit("onTaskFinished", task_id, False, str(e), "", 0)

    def ai_tag_all(self, tasks: List[Dict[str, Any]]):
        threading.Thread(target=self._run_ai_worker, args=(tasks,), daemon=True).start()
        return {"status": "started"}

    def _run_ai_worker(self, tasks: List[Dict[str, Any]]):
        self._log(f">>> 开始对 {len(tasks)} 个任务匹配 Emoji...")
        config = AIEmojiConfig.load()

        for idx, t in enumerate(tasks):
            tid = t.get("task_id", 0)
            in_path = t.get("input_path", "")
            start_t = t.get("start_time")
            end_t = t.get("end_time")
            fname = os.path.basename(in_path)
            self._emit("onAiItemStarted", tid, fname)
            try:
                emoji = AIEmojiTagger.predict_emoji(
                    in_path, config, start_time=start_t, end_time=end_t
                )
                self._log(f"[AI Emoji] {fname} -> {emoji or '无匹配'}")
                self._emit("onAiItemFinished", tid, emoji)
            except Exception as e:
                self._log(f"[AI 提示] {fname}: {e}")
                self._emit("onAiItemError", tid, str(e))

            if idx < len(tasks) - 1:
                time.sleep(0.2)

        self._log(">>> AI Emoji 识别流程完成。")
        self._emit("onAiAllCompleted")
