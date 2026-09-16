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
from core.pack_output import (
    PackEntry,
    PackError,
    default_zip_name,
    normalize_keywords,
    pack_stickers,
    unique_arcname,
)
from core.sticker_list import (
    StickerListError,
    default_bundle_name,
    default_bundle_zip_name,
    export_prepared_stickers,
    import_sticker_bundle,
    looks_like_import_path,
    write_sticker_bundle,
)
from core.settings_store import default_output_dir, default_settings
from core.settings_store import load_settings as load_app_settings
from core.settings_store import save_settings as save_app_settings
from core.proxy_manager import get_proxy_manager, needs_proxy
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

    def select_import_source(self) -> str:
        if not webview.windows:
            return ""
        result = webview.windows[0].create_file_dialog(
            _file_dialog_type("OPEN"),
            allow_multiple=False,
            file_types=(
                "贴纸导出 (*.zip;*.json)",
                "ZIP 压缩包 (*.zip)",
                "JSON 列表 (*.json)",
                "All Files (*.*)",
            ),
        )
        if not result:
            return ""
        chosen = result[0] if isinstance(result, (list, tuple)) else str(result)
        return str(chosen or "")

    def detect_import_source(self, path: str) -> Dict[str, Any]:
        return {"status": "ok", "found": looks_like_import_path(path)}

    def import_sticker_list(self, source_path: str = "") -> Dict[str, Any]:
        path = (source_path or "").strip()
        if not path:
            path = self.select_import_source()
            if not path:
                return {"status": "empty", "error": "已取消导入"}
        self._canceled = False
        if webview.windows:
            threading.Thread(target=self._run_import_worker, args=(path,), daemon=True).start()
            return {"status": "started"}
        return self._run_import_worker(path)

    def _run_import_worker(self, path: str) -> Dict[str, Any]:
        self._log(">>> 开始导入贴纸列表...")
        self._emit("onImportProgress", 0, 1, "正在读取导出列表...")
        try:
            if path.lower().endswith(".zip"):
                self._emit("onImportProgress", 0, 1, "正在解压...")
            result = import_sticker_bundle(path)
            if self._canceled:
                raise StickerListError("已取消导入")
            missing = result.get("missing") or []
            self._log(f"📥 已解析导入列表：{result['count']} 项")
            if missing:
                self._log(f"⚠️ 有 {len(missing)} 个源文件缺失，已跳过")
            self._emit("onImportProgress", 0, int(result["count"] or 0), "正在加入任务列表...")
            self._emit(
                "onImportFinished",
                True,
                result.get("stickers") or [],
                missing,
                "",
            )
            return {"status": "ok", **result}
        except StickerListError as e:
            self._log(f"⚠️ 导入跳过: {e}")
            self._emit("onImportFinished", False, [], [], str(e))
            return {"status": "empty", "error": str(e)}
        except Exception as e:
            self._log(f"❌ 导入失败: {e}")
            self._emit("onImportFinished", False, [], [], str(e))
            return {"status": "error", "error": str(e)}

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

    def get_proxy_status(self, file_path: str, start: bool = False) -> Dict[str, Any]:
        if not file_path or not os.path.isfile(file_path):
            return {"status": "error", "needs_proxy": False, "progress": 0, "error": "File not found"}
        pm = get_proxy_manager()
        is_needed = needs_proxy(file_path)
        if is_needed and start:
            pm.ensure_proxy_async(file_path)
        task = pm.get_proxy_status(file_path)
        return {
            "status": task.status,
            "progress": round(task.progress, 3),
            "error": task.error,
            "needs_proxy": is_needed,
        }

    def get_proxy_cache_info(self) -> Dict[str, Any]:
        return get_proxy_manager().cache_info()

    def clear_proxy_cache(self) -> Dict[str, Any]:
        return get_proxy_manager().clear_cache()

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
        self._log(">>> 用户请求取消。")

    def start_conversion(self, tasks: List[Dict[str, Any]], global_options: Dict[str, Any]):
        self._canceled = False
        threading.Thread(target=self._run_conversion_worker, args=(tasks, global_options), daemon=True).start()
        return {"status": "started"}

    def export_sticker_list(
        self,
        stickers: List[Dict[str, Any]],
        dest_path: str = "",
        directory: str = "",
        mode: str = "list",
        global_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        export_mode = "sources" if mode == "sources" else "list"
        opts = global_options or {}
        pack_output = bool(opts.get("pack_output", True))
        try:
            dest = (dest_path or "").strip()
            if export_mode == "sources" and not dest and not pack_output:
                dest = self._resolve_bundle_dir(directory=directory)
        except StickerListError as e:
            self._log(f"⚠️ 导出列表跳过: {e}")
            return {"status": "empty", "error": str(e)}
        except Exception as e:
            self._log(f"❌ 导出列表失败: {e}")
            return {"status": "error", "error": str(e)}

        self._canceled = False
        args = (stickers, dest, directory, export_mode, opts)
        if webview.windows:
            threading.Thread(target=self._run_export_worker, args=args, daemon=True).start()
            return {"status": "started"}
        return self._run_export_worker(*args)

    def _run_export_worker(
        self,
        stickers: List[Dict[str, Any]],
        dest: str,
        directory: str,
        export_mode: str,
        opts: Dict[str, Any],
    ) -> Dict[str, Any]:
        completed: set = set()
        total = sum(1 for item in stickers if str(item.get("input_path") or "").strip())
        self._log(f">>> 开始导出 {total} 项...")
        self._emit("onExportProgress", 0, max(total, 1), "准备导出...")

        def progress_callback(index: int, n: int, item: Dict[str, Any], **kwargs: Any) -> None:
            if self._canceled:
                raise StickerListError("已取消导出")
            phase = str(kwargs.get("phase") or "")
            dest_item = str(kwargs.get("dest") or "")
            error = str(kwargs.get("error") or "")
            size = int(kwargs.get("size") or 0)
            task_id = item.get("task_id")
            name = os.path.basename(
                str(item.get("file_name") or item.get("input_path") or dest_item or "")
            )
            count = n or max(total, 1)
            if phase == "start":
                self._log(f"📤 [{index}/{count}] 正在导出 {name}")
                self._emit("onExportProgress", max(index - 1, 0), count, f"正在导出 {name}")
                if task_id is not None:
                    self._emit("onTaskStarted", task_id)
                    self._emit("onTaskProgress", task_id, 0.08, "正在导出...")
            elif phase == "done":
                self._emit("onExportProgress", index, count, f"已导出 {name}")
                if task_id is not None:
                    completed.add(task_id)
                    self._emit("onTaskFinished", task_id, True, "已导出", dest_item, size)
            elif phase == "skip":
                self._log(f"⚠️ [{index}/{count}] 源文件缺失: {name}")
                if task_id is not None:
                    completed.add(task_id)
                    self._emit("onTaskFinished", task_id, False, "源文件缺失", "", 0)
            elif phase == "error":
                self._log(f"❌ [{index}/{count}] 导出失败: {error}")
                if task_id is not None:
                    completed.add(task_id)
                    self._emit("onTaskFinished", task_id, False, error or "导出失败", "", 0)
            elif phase == "pack":
                self._log("📦 正在打包压缩包...")
                self._emit("onExportProgress", count, count, "正在打包压缩包...")

        def finish_remaining(msg: str) -> None:
            for item in stickers:
                task_id = item.get("task_id")
                if task_id is None or task_id in completed:
                    continue
                self._emit("onTaskFinished", task_id, False, msg, "", 0)

        try:
            if export_mode == "sources":
                result = self._export_sources(
                    stickers,
                    dest,
                    directory=directory,
                    opts=opts,
                    progress_callback=progress_callback,
                    cancel_check=lambda: self._canceled,
                )
                missing = result.get("missing") or []
                self._log(
                    f"📤 已导出源文件+JSON：{result['count']} 项，复制 {result['copied']} 个文件 -> {result['path']}"
                )
            else:
                result = self._export_prepared(
                    stickers,
                    dest,
                    directory=directory,
                    opts=opts,
                    progress_callback=progress_callback,
                    cancel_check=lambda: self._canceled,
                )
                missing = result.get("missing") or []
                self._log(f"📤 已导出转换前文件 {result['count']} 项 -> {result['path']}")
            if missing:
                self._log(f"⚠️ 有 {len(missing)} 个源文件缺失，已跳过")
            zip_path = str(result.get("zip_path") or "")
            if zip_path:
                self._emit("onPackFinished", True, zip_path, result.get("count") or 0)
            self._emit("onExportFinished", True, result.get("path") or "", result.get("count") or 0, "")
            return {"status": "ok", **result}
        except StickerListError as e:
            finish_remaining(str(e))
            self._log(f"⚠️ 导出列表跳过: {e}")
            self._emit("onExportFinished", False, "", 0, str(e))
            return {"status": "empty", "error": str(e)}
        except Exception as e:
            finish_remaining(str(e))
            self._log(f"❌ 导出列表失败: {e}")
            self._emit("onExportFinished", False, "", 0, str(e))
            return {"status": "error", "error": str(e)}

    def _export_sources(
        self,
        stickers: List[Dict[str, Any]],
        dest_path: str,
        directory: str,
        opts: Dict[str, Any],
        progress_callback=None,
        cancel_check=None,
    ) -> Dict[str, Any]:
        pack_output = bool(opts.get("pack_output", True))
        dest = (dest_path or "").strip()
        extra = {"progress_callback": progress_callback, "cancel_check": cancel_check}
        if dest.lower().endswith(".zip"):
            staging = tempfile.mkdtemp(prefix="tg_stickers_bundle_")
            try:
                return write_sticker_bundle(staging, stickers, zip_path=dest, **extra)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        if dest:
            return write_sticker_bundle(dest, stickers, **extra)

        out_dir = (directory or "").strip() or self._pack_zip_dir(opts)
        if pack_output:
            staging = tempfile.mkdtemp(prefix="tg_stickers_bundle_")
            try:
                os.makedirs(out_dir, exist_ok=True)
                zip_path = os.path.join(os.path.abspath(out_dir), default_bundle_zip_name())
                return write_sticker_bundle(staging, stickers, zip_path=zip_path, **extra)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        dest = self._resolve_bundle_dir(directory=directory)
        return write_sticker_bundle(dest, stickers, **extra)

    def _export_prepared(
        self,
        stickers: List[Dict[str, Any]],
        dest_path: str,
        directory: str,
        opts: Dict[str, Any],
        progress_callback=None,
        cancel_check=None,
    ) -> Dict[str, Any]:
        pack_output = bool(opts.get("pack_output", True))
        dest = (dest_path or "").strip()
        extra = {"progress_callback": progress_callback, "cancel_check": cancel_check}
        if dest.lower().endswith(".zip"):
            staging = tempfile.mkdtemp(prefix="tg_stickers_export_")
            try:
                return export_prepared_stickers(stickers, staging, zip_path=dest, **extra)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        if dest:
            return export_prepared_stickers(stickers, dest, **extra)

        out_dir = (directory or "").strip() or self._pack_zip_dir(opts)
        if pack_output:
            staging = tempfile.mkdtemp(prefix="tg_stickers_export_")
            try:
                zip_path = self._resolve_zip_path(zip_dir=out_dir)
                return export_prepared_stickers(stickers, staging, zip_path=zip_path, **extra)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        if opts.get("same_dir"):
            return self._export_prepared_same_dir(
                stickers,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )
        os.makedirs(out_dir, exist_ok=True)
        return export_prepared_stickers(stickers, out_dir, **extra)

    def _export_prepared_same_dir(
        self,
        stickers: List[Dict[str, Any]],
        progress_callback=None,
        cancel_check=None,
    ) -> Dict[str, Any]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for item in stickers:
            src = str(item.get("input_path") or "").strip()
            if not src:
                continue
            grouped.setdefault(os.path.dirname(os.path.abspath(src)), []).append(item)
        if not grouped:
            raise StickerListError("贴纸列表为空")
        total_items = sum(len(rows) for rows in grouped.values())
        offset = 0
        total = 0
        missing: List[str] = []
        last_path = ""
        for folder, rows in grouped.items():
            def make_cb(base: int):
                def cb(index: int, _n: int, item: Dict[str, Any], **kwargs: Any) -> None:
                    if progress_callback:
                        progress_callback(base + index, total_items, item, **kwargs)
                return cb

            result = export_prepared_stickers(
                rows,
                folder,
                progress_callback=make_cb(offset) if progress_callback else None,
                cancel_check=cancel_check,
            )
            offset += int(result["count"]) + len(result.get("missing") or [])
            total += int(result["count"])
            missing.extend(result.get("missing") or [])
            last_path = str(result["path"])
        return {"path": last_path, "count": total, "missing": missing}

    def _resolve_bundle_dir(self, directory: str = "") -> str:
        bundle_name = default_bundle_name()
        if webview.windows:
            suggested_dir = (directory or "").strip() or default_output_dir()
            result = None
            try:
                os.makedirs(suggested_dir, exist_ok=True)
                result = webview.windows[0].create_file_dialog(
                    _file_dialog_type("FOLDER"),
                    directory=suggested_dir,
                )
            except Exception:
                result = None
            if result:
                chosen = result[0] if isinstance(result, (list, tuple)) else str(result)
                if chosen:
                    dest = os.path.join(os.path.abspath(chosen), bundle_name)
                    os.makedirs(dest, exist_ok=True)
                    return dest
            raise StickerListError("已取消导出")
        dest_dir = (directory or "").strip() or default_output_dir()
        dest = os.path.join(os.path.abspath(dest_dir), bundle_name)
        os.makedirs(dest, exist_ok=True)
        return dest

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
                    keywords=normalize_keywords(item.get("keywords")),
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
                            PackEntry(
                                path=item["path"],
                                emoji=item.get("emoji") or "",
                                keywords=normalize_keywords(item.get("keywords")),
                            )
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
        keywords = normalize_keywords(task.get("keywords"))

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
                return {
                    "path": out_path,
                    "emoji": emoji,
                    "keywords": keywords,
                    "final_path": display_path,
                }
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
