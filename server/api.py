import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

import webview

from core import __version__
from core.ai_tagger import AIEmojiConfig, AIEmojiTagger
from core.analyzer import MediaAnalyzer
from core.encoder import EncodeOptions, StickerEncoder
from core.pack_output import PackEntry, PackError, default_zip_name, pack_stickers, unique_arcname
from core.settings_store import default_output_dir, default_settings
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
        if not os.path.isdir(abs_path):
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

    def pack_outputs(
        self,
        files: List[Dict[str, Any]],
        zip_dir: str = "",
        zip_path: str = "",
        prompt: bool = False,
        is_custom_emoji: Optional[bool] = None,
    ) -> Dict[str, Any]:
        try:
            dest = self._resolve_zip_path(zip_dir=zip_dir, zip_path=zip_path, prompt=prompt)
            entries = [
                PackEntry(
                    path=str(item.get("path") or ""),
                    emoji=str(item.get("emoji") or ""),
                    arcname=str(item.get("arcname") or ""),
                )
                for item in files
            ]
            result = pack_stickers(entries, dest)
            self._log(f"📦 已打包 {result['count']} 个贴纸 -> {result['path']}")
            self._emit("onPackFinished", True, result["path"], result["count"])
            return {"status": "ok", **result}
        except PackError as e:
            self._log(f"⚠️ 打包跳过: {e}")
            self._emit("onPackFinished", False, "", 0)
            return {"status": "empty", "error": str(e)}
        except Exception as e:
            self._log(f"❌ 打包失败: {e}")
            self._emit("onPackFinished", False, "", 0)
            return {"status": "error", "error": str(e)}

    def _resolve_zip_path(self, zip_dir: str = "", zip_path: str = "", prompt: bool = False) -> str:
        if zip_path:
            dest = os.path.abspath(zip_path)
            if not dest.lower().endswith(".zip"):
                dest += ".zip"
            return dest
        if prompt and webview.windows:
            suggested_dir = zip_dir or default_output_dir()
            result = None
            try:
                os.makedirs(suggested_dir, exist_ok=True)
                result = webview.windows[0].create_file_dialog(
                    _file_dialog_type("SAVE"),
                    directory=suggested_dir,
                    save_filename=default_zip_name(),
                    file_types=("ZIP 压缩包 (*.zip)",),
                )
            except Exception:
                result = None
            if result:
                chosen = result[0] if isinstance(result, (list, tuple)) else str(result)
                if chosen:
                    dest = os.path.abspath(chosen)
                    if not dest.lower().endswith(".zip"):
                        dest += ".zip"
                    return dest
            raise PackError("已取消打包")
        dest_dir = (zip_dir or "").strip() or default_output_dir()
        os.makedirs(dest_dir, exist_ok=True)
        return os.path.join(os.path.abspath(dest_dir), default_zip_name())

    def _pack_zip_dir(self, global_options: Dict[str, Any]) -> str:
        custom = str(global_options.get("custom_output_dir") or "").strip()
        if custom:
            return custom
        return default_output_dir()

    def _stage_pack_tasks(self, tasks: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        staging = tempfile.mkdtemp(prefix="tg_stickers_")
        used: set[str] = set()
        staged: List[Dict[str, Any]] = []
        for task in tasks:
            item = dict(task)
            final_path = str(item.get("output_path") or "")
            item["final_output_path"] = final_path
            name = unique_arcname(os.path.basename(final_path) or "sticker.webm", used)
            item["output_path"] = os.path.join(staging, name)
            staged.append(item)
        return staging, staged

    def _copy_pack_fallback(self, successes: List[Dict[str, Any]]) -> None:
        for item in successes:
            src = item.get("path") or ""
            dest = item.get("final_path") or ""
            if not src or not dest or not os.path.isfile(src):
                continue
            os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
            shutil.copy2(src, dest)

    def _log(self, message: str):
        self._emit("onLog", message)

    def _run_conversion_worker(self, tasks: List[Dict[str, Any]], global_options: Dict[str, Any]):
        self._log(f">>> 开始执行 {len(tasks)} 个转换任务（最多 {self.CONVERT_WORKERS} 路并行）...")
        pack_output = bool(global_options.get("pack_output", True))
        staging = None
        work_tasks = tasks
        try:
            if pack_output:
                staging, work_tasks = self._stage_pack_tasks(tasks)
            futures = [
                self._executor.submit(self._convert_one, task, global_options)
                for task in work_tasks
            ]
            wait(futures)
            successes: List[Dict[str, Any]] = []
            for fut in futures:
                try:
                    item = fut.result()
                    if item:
                        successes.append(item)
                except Exception as exc:
                    self._log(f"❌ 转换线程异常: {exc}")
            if self._canceled:
                self._log(">>> 批量转换已取消。")
            if pack_output and successes:
                try:
                    dest = self._resolve_zip_path(zip_dir=self._pack_zip_dir(global_options))
                    result = pack_stickers(
                        [
                            PackEntry(path=item["path"], emoji=item.get("emoji") or "")
                            for item in successes
                        ],
                        dest,
                    )
                    self._log(f"📦 已打包 {result['count']} 个贴纸 -> {result['path']}")
                    self._emit("onPackFinished", True, result["path"], result["count"])
                except Exception as e:
                    self._log(f"❌ 打包失败，改为输出散文件: {e}")
                    self._copy_pack_fallback(successes)
                    self._emit("onPackFinished", False, "", 0)
        finally:
            if staging:
                shutil.rmtree(staging, ignore_errors=True)
        self._log(">>> 所有转换任务已结束。")
        self._emit("onAllCompleted")

    def _convert_one(self, task: Dict[str, Any], global_options: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        task_id = task.get("task_id", 0)
        in_path = task.get("input_path", "")
        out_path = task.get("output_path", "")
        display_path = str(task.get("final_output_path") or out_path)
        emoji = str(task.get("emoji") or "")

        if self._canceled:
            self._emit("onTaskFinished", task_id, False, "已取消", "", 0)
            return None

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
                self._emit("onTaskFinished", task_id, True, msg, display_path, sz)
                return {"path": out_path, "emoji": emoji, "final_path": display_path}
            msg = "转码未生成有效文件"
            self._log(f"❌ [{os.path.basename(in_path)}] 失败: {msg}")
            self._emit("onTaskFinished", task_id, False, msg, "", 0)
            return None
        except InterruptedError:
            self._log(f"[{os.path.basename(in_path)}] 任务已取消。")
            self._emit("onTaskFinished", task_id, False, "已取消", "", 0)
            return None
        except Exception as e:
            self._log(f"❌ [{os.path.basename(in_path)}] 报错: {str(e)}")
            self._emit("onTaskFinished", task_id, False, str(e), "", 0)
            return None

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
