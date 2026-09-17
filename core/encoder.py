import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from typing import Callable, Optional
from PIL import Image, ImageChops, ImageOps, ImageStat

from core.analyzer import MediaAnalyzer, MediaInfo
from core.ebml_patcher import EBMLPatcher
from core.crop_shape import build_radius_mask_filter, normalize_crop_radius
from core.encode_plan import (
    VideoEncodePlan,
    build_vf,
    choose_bitrate_kbps,
    lower_fps,
    plan_video,
)
from core.proc import ffmpeg_bin, run_hidden


@dataclass
class EncodeOptions:
    preset_style: str = "anime"  # "anime", "cinema", "fast"
    spoof_duration: bool = True  # modify header to 2.99s if > 3s
    optimize_fps: bool = True  # drop fps on long/high-motion clips to save bits
    custom_fps: Optional[int] = None
    output_size_limit_kb: int = 256  # 256KB for video stickers, 512KB for static
    is_custom_emoji: bool = False  # 100x100 for custom emoji
    crf: Optional[int] = None
    crop_to_3s: bool = False  # hard cut first 3s instead of spoofing
    start_time: Optional[float] = None  # clip start offset in seconds
    end_time: Optional[float] = None  # clip end offset in seconds
    crop: Optional[tuple[int, int, int, int]] = None  # (crop_x, crop_y, crop_w, crop_h)
    crop_radius: float = 0.0  # 0 = rectangle, 1 = circle / pill
    mirror: bool = False  # horizontal flip (hflip)


def mean_luma_sad(prev: bytes, cur: bytes, width: int, height: int) -> float:
    """Mean |Δ luma| / 255 between two packed gray frames (Pillow, not a Python pixel loop)."""
    a = Image.frombytes("L", (width, height), prev)
    b = Image.frombytes("L", (width, height), cur)
    return float(ImageStat.Stat(ImageChops.difference(a, b)).mean[0]) / 255.0


class StickerEncoder:
    """
    High-quality Telegram Sticker Encoder.
    Converts images to 512px WebP (<=512KB) and videos to 512px WebM VP9 (<=256KB).
    Applies Lanczos scaling, 2-pass VP9 VBR, motion-aware fps, and optional EBML spoofing.
    """

    MAX_VIDEO_SIZE = 256 * 1024  # 256 KB
    MAX_STATIC_SIZE = 512 * 1024  # 512 KB
    MAX_EMOJI_SIZE = 64 * 1024  # 64 KB for Telegram Custom Emoji

    @staticmethod
    def get_ffmpeg_path() -> str:
        return ffmpeg_bin()

    @classmethod
    def convert(
        cls,
        input_path: str,
        output_path: str,
        options: Optional[EncodeOptions] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> bool:
        if options is None:
            options = EncodeOptions()

        media_info = MediaAnalyzer.analyze(input_path)

        if progress_callback:
            progress_callback(0.05, f"分析媒体信息完成: {media_info.width}x{media_info.height}")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        if not media_info.is_video:
            return cls._convert_static(
                input_path, output_path, media_info, options, progress_callback
            )
        return cls._convert_video(
            input_path, output_path, media_info, options, progress_callback
        )

    @classmethod
    def _convert_static(
        cls,
        input_path: str,
        output_path: str,
        info: MediaInfo,
        options: EncodeOptions,
        callback: Optional[Callable[[float, str], None]],
    ) -> bool:
        ffmpeg = cls.get_ffmpeg_path()
        if not output_path.lower().endswith(".webp"):
            output_path = os.path.splitext(output_path)[0] + ".webp"

        temp_dir = None
        actual_input_path = input_path
        ext = os.path.splitext(input_path)[1].lower()
        if ext in {".heic", ".heif"}:
            try:
                temp_dir = tempfile.mkdtemp(prefix="sticker_heic_")
                temp_png = os.path.join(temp_dir, "preprocessed.png")
                with Image.open(input_path) as img:
                    img = ImageOps.exif_transpose(img)
                    img.save(temp_png, "PNG")
                actual_input_path = temp_png
            except Exception:
                actual_input_path = input_path

        try:
            if callback:
                callback(0.3, "正在缩放图像 (Lanczos)...")

            max_size = cls.MAX_EMOJI_SIZE if options.is_custom_emoji else cls.MAX_STATIC_SIZE
            max_limit_kb = max_size // 1024
            scale_flags = "lanczos+accurate_rnd+full_chroma_int"

            if options.is_custom_emoji:
                scale_filter = (
                    f"scale='if(gte(iw,ih),100,-1)':'if(gte(iw,ih),-1,100)':flags={scale_flags},"
                    "pad=100:100:(100-iw)/2:(100-ih)/2:color=black@0"
                )
            else:
                scale_filter = (
                    f"scale='if(gte(iw,ih),512,-1)':'if(gte(iw,ih),-1,512)':flags={scale_flags}"
                )

            if options.crop:
                cx, cy, cw, ch = options.crop
                cw = max(2, cw - (cw % 2))
                ch = max(2, ch - (ch % 2))
                cx = max(0, cx - (cx % 2))
                cy = max(0, cy - (cy % 2))
                scale_filter = f"crop={cw}:{ch}:{cx}:{cy}," + scale_filter

            if options.mirror:
                scale_filter = "hflip," + scale_filter

            mask = build_radius_mask_filter(normalize_crop_radius(options.crop_radius))
            if mask:
                scale_filter = scale_filter + "," + mask

            if callback:
                callback(0.4, "正在以无损模式编码 WebP...")

            clean_extra = [
                "-map", "0:v:0",
                "-an",
                "-sn",
                "-dn",
                "-map_chapters", "-1",
                "-map_metadata", "-1",
            ]
            cmd_lossless = [
                ffmpeg, "-y", "-i", actual_input_path,
                "-vf", scale_filter,
                "-vcodec", "libwebp",
                "-lossless", "1",
                "-compression_level", "6",
                *clean_extra,
                output_path,
            ]
            res = run_hidden(cmd_lossless, text=True)

            is_lossless = False
            if res.returncode == 0 and os.path.exists(output_path):
                if os.path.getsize(output_path) <= max_size:
                    is_lossless = True

            if not is_lossless:
                if callback:
                    callback(0.55, f"无损体积超出 {max_limit_kb}KB 限制，尝试 near-lossless...")

                success = False
                cmd_near = [
                    ffmpeg, "-y", "-i", actual_input_path,
                    "-vf", scale_filter,
                    "-vcodec", "libwebp",
                    "-lossless", "0",
                    "-near_lossless", "40",
                    "-compression_level", "6",
                    *clean_extra,
                    output_path,
                ]
                res_near = run_hidden(cmd_near, text=True)
                if (
                    res_near.returncode == 0
                    and os.path.exists(output_path)
                    and os.path.getsize(output_path) <= max_size
                ):
                    success = True
                    mode_desc = "near-lossless"
                else:
                    if callback:
                        callback(0.6, "切换至有损压缩模式...")
                    for quality in ["98", "95", "90", "85", "80", "70", "60"]:
                        cmd_lossy = [
                            ffmpeg, "-y", "-i", actual_input_path,
                            "-vf", scale_filter,
                            "-vcodec", "libwebp",
                            "-lossless", "0",
                            "-quality", quality,
                            "-compression_level", "6",
                            *clean_extra,
                            output_path,
                        ]
                        res_lossy = run_hidden(cmd_lossy, text=True)
                        if (
                            res_lossy.returncode == 0
                            and os.path.exists(output_path)
                            and os.path.getsize(output_path) <= max_size
                        ):
                            success = True
                            mode_desc = f"有损 Q{quality}"
                            break

                if not success:
                    if callback:
                        callback(1.0, f"静态转换失败或体积超出 {max_limit_kb}KB")
                    return False
            else:
                mode_desc = "纯无损"

            if callback:
                final_kb = os.path.getsize(output_path) / 1024
                callback(1.0, f"转换完成（{mode_desc}），体积: {final_kb:.1f} KB")

            return True
        finally:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    @classmethod
    def _seek_args(
        cls,
        start_time: Optional[float],
        duration: Optional[float],
    ) -> tuple[list[str], list[str]]:
        if start_time is None or start_time <= 0.0:
            post = ["-t", f"{duration:.3f}"] if duration is not None else []
            return [], post

        if start_time > 10.0:
            pre_seek = max(0.0, start_time - 4.0)
            post_seek = start_time - pre_seek
            pre = ["-ss", f"{pre_seek:.3f}"]
            post = ["-ss", f"{post_seek:.3f}"]
        else:
            pre = []
            post = ["-ss", f"{start_time:.3f}"]

        if duration is not None:
            post.extend(["-t", f"{duration:.3f}"])
        return pre, post

    @classmethod
    def _estimate_motion(
        cls,
        input_path: str,
        duration: float,
        start_time: Optional[float] = None,
        crop: Optional[tuple[int, int, int, int]] = None,
        mirror: bool = False,
    ) -> Optional[float]:
        """Mean |Δ luma|/255 on ~16 gray 160x90 frames. None on failure."""
        ffmpeg = cls.get_ffmpeg_path()
        sample_fps = max(0.5, min(8.0, 16.0 / max(duration, 0.5)))
        width, height = 160, 90
        crop_filter = ""
        if mirror:
            crop_filter += "hflip,"
        if crop is not None:
            cx, cy, cw, ch = crop
            cw = max(2, cw - (cw % 2))
            ch = max(2, ch - (ch % 2))
            cx = max(0, cx - (cx % 2))
            cy = max(0, cy - (cy % 2))
            crop_filter += f"crop={cw}:{ch}:{cx}:{cy},"
        vf = (
            f"{crop_filter}scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={sample_fps:.4f},format=gray"
        )
        pre_seek, post_seek = cls._seek_args(start_time, duration)
        cmd = [
            ffmpeg, "-v", "error",
            *pre_seek,
            "-i", input_path,
            *post_seek,
            "-map", "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-vf", vf,
            "-pix_fmt", "gray",
            "-f", "rawvideo",
            "pipe:1",
        ]
        try:
            res = run_hidden(cmd, timeout=25)
        except (subprocess.TimeoutExpired, OSError):
            return None

        frame_size = width * height
        raw = res.stdout or b""
        n_frames = len(raw) // frame_size
        if n_frames < 2:
            return None

        total = 0.0
        pairs = 0
        prev = raw[0:frame_size]
        for i in range(1, n_frames):
            cur = raw[i * frame_size : (i + 1) * frame_size]
            total += mean_luma_sad(prev, cur, width, height)
            pairs += 1
            prev = cur
        return total / pairs if pairs else None

    @classmethod
    def _vp9_args(cls, plan: VideoEncodePlan) -> list[str]:
        args = [
            "-map", "0:v:0",
            "-c:v", "libvpx-vp9",
            "-b:v", f"{plan.bitrate_kbps}k",
            "-aq-mode", "2",
            "-auto-alt-ref", str(plan.auto_alt_ref),
            "-g", str(plan.gop),
            "-tile-columns", "0",
            "-frame-parallel", "0",
            "-row-mt", "1",
            "-pix_fmt", plan.pix_fmt,
            "-colorspace", "bt709",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-color_range", "tv",
            "-an",
            "-sn",
            "-dn",
            "-map_chapters", "-1",
            "-map_metadata", "-1",
        ]
        if plan.auto_alt_ref:
            args.extend([
                "-lag-in-frames", "25",
                "-arnr-maxframes", "7",
                "-arnr-strength", "4",
                "-enable-tpl", "1",
            ])
        if plan.crf is not None:
            args.extend(["-crf", str(plan.crf)])
        return args

    @staticmethod
    def _replace_arg(cmd_list: list[str], flag: str, new_val: str) -> None:
        if flag in cmd_list:
            cmd_list[cmd_list.index(flag) + 1] = str(new_val)
        else:
            cmd_list.extend([flag, str(new_val)])

    @classmethod
    def _run_ffmpeg(cls, cmd: list[str]) -> subprocess.CompletedProcess:
        return run_hidden(cmd, text=True)

    @classmethod
    def _encode_vp9(
        cls,
        ffmpeg: str,
        input_path: str,
        output_path: str,
        plan: VideoEncodePlan,
        should_crop: bool,
        pass_log: str,
        null_out: str,
        callback: Optional[Callable[[float, str], None]],
        start_time: Optional[float] = None,
        clip_duration: Optional[float] = None,
    ) -> bool:
        if start_time is not None and clip_duration is not None:
            pre_args, post_args = cls._seek_args(start_time, clip_duration)
        elif should_crop:
            pre_args = []
            post_args = ["-t", "3.0"]
        else:
            pre_args = []
            post_args = []

        common = [*pre_args, "-i", input_path, *post_args, "-vf", plan.vf, *cls._vp9_args(plan)]

        if plan.two_pass:
            if callback:
                callback(0.22, f"Pass 1: 扫描运动与比特分布 ({plan.bitrate_kbps}k)...")
            pass1 = [
                ffmpeg, "-y", *common,
                "-pass", "1", "-passlogfile", pass_log,
                "-deadline", plan.deadline, "-cpu-used", str(plan.cpu_used_pass1),
                "-f", "null", null_out,
            ]
            res1 = cls._run_ffmpeg(pass1)
            if res1.returncode != 0:
                if callback:
                    callback(1.0, f"Pass 1 失败: {(res1.stderr or '')[-200:]}")
                return False

            if callback:
                mode = f"CRF {plan.crf}" if plan.crf is not None else "ABR VBR"
                callback(0.55, f"Pass 2: {mode}, AQ-Mode 2, {plan.pix_fmt}...")
            pass2 = [
                ffmpeg, "-y", *common,
                "-pass", "2", "-passlogfile", pass_log,
                "-deadline", plan.deadline, "-cpu-used", str(plan.cpu_used_pass2),
                output_path,
            ]
            res2 = cls._run_ffmpeg(pass2)
            if res2.returncode != 0:
                if callback:
                    callback(1.0, f"Pass 2 失败: {(res2.stderr or '')[-200:]}")
                return False
            return True

        if callback:
            callback(0.45, f"单遍编码 ({plan.bitrate_kbps}k, cpu-used {plan.cpu_used_pass2})...")
        single = [
            ffmpeg, "-y", *common,
            "-deadline", plan.deadline, "-cpu-used", str(plan.cpu_used_pass2),
            output_path,
        ]
        res = cls._run_ffmpeg(single)
        if res.returncode != 0:
            if callback:
                callback(1.0, f"编码失败: {(res.stderr or '')[-200:]}")
            return False
        return True

    @classmethod
    def _convert_video(
        cls,
        input_path: str,
        output_path: str,
        info: MediaInfo,
        options: EncodeOptions,
        callback: Optional[Callable[[float, str], None]],
    ) -> bool:
        ffmpeg = cls.get_ffmpeg_path()
        if not output_path.lower().endswith(".webm"):
            output_path = os.path.splitext(output_path)[0] + ".webm"

        max_size = cls.MAX_EMOJI_SIZE if options.is_custom_emoji else cls.MAX_VIDEO_SIZE
        max_limit_kb = max_size // 1024

        start_time = options.start_time
        end_time = options.end_time
        is_clip = (
            start_time is not None
            and end_time is not None
            and end_time > start_time
        )
        if is_clip:
            real_duration = end_time - start_time
            should_crop = False
            clip_duration = real_duration
        else:
            real_duration = info.duration if info.duration > 0.05 else 3.0
            should_crop = options.crop_to_3s and real_duration > 3.0
            clip_duration = None

        motion_score = None
        if (
            options.optimize_fps
            and options.custom_fps is None
            and real_duration > 4.0
            and not should_crop
        ):
            if callback:
                callback(0.12, "正在估算画面运动复杂度...")
            motion_score = cls._estimate_motion(
                input_path,
                real_duration,
                start_time=start_time if is_clip else None,
                crop=options.crop,
                mirror=options.mirror,
            )

        plan = plan_video(info, options, motion_score=motion_score)
        if callback:
            callback(0.18, f"编码规划: {plan.reason}")

        temp_dir = tempfile.mkdtemp(prefix="tg_sticker_")
        pass_log = os.path.join(temp_dir, "ffmpeg2pass")
        null_out = "NUL" if os.name == "nt" else "/dev/null"

        try:
            filled = False
            for attempt in range(4):
                ok = cls._encode_vp9(
                    ffmpeg, input_path, output_path, plan,
                    should_crop, pass_log, null_out, callback,
                    start_time=start_time if is_clip else None,
                    clip_duration=clip_duration if is_clip else None,
                )
                if not ok:
                    return False
                if not os.path.exists(output_path):
                    if callback:
                        callback(1.0, "编码未生成输出文件")
                    return False

                file_size = os.path.getsize(output_path)
                if file_size > max_size:
                    new_kbps = max(16, int(plan.bitrate_kbps * (max_size / file_size) * 0.97))
                    next_step = lower_fps(plan.fps)
                    # First overshoot: cut bitrate. Later: drop fps if we still can.
                    drop_fps = (
                        attempt > 0
                        and next_step is not None
                        and options.custom_fps is None
                    )
                    if drop_fps:
                        if callback:
                            callback(
                                0.82,
                                f"体积 {file_size/1024:.1f}KB 超限，{plan.fps:g}→{next_step}fps 重压...",
                            )
                        plan = replace(
                            plan,
                            fps=float(next_step),
                            vf=build_vf(
                                is_emoji=options.is_custom_emoji,
                                preset_style=options.preset_style or "anime",
                                fps=float(next_step),
                                source_fps=plan.source_fps,
                                crop=options.crop,
                                crop_radius=options.crop_radius,
                                mirror=options.mirror,
                            ),
                            bitrate_kbps=min(plan.bitrate_kbps, new_kbps),
                            crf=None,
                        )
                    else:
                        if callback:
                            callback(
                                0.82,
                                f"体积 {file_size/1024:.1f}KB 超限，码率 {plan.bitrate_kbps}k→{new_kbps}k...",
                            )
                        plan = replace(plan, bitrate_kbps=new_kbps, crf=None)
                    continue

                undershoot = file_size < max_size * 0.90
                if undershoot and plan.crf is None and not filled:
                    bump = int(plan.bitrate_kbps * (plan.payload_bytes / max(file_size, 1)))
                    cap = choose_bitrate_kbps(plan.payload_bytes, plan.duration)
                    bump = min(bump, int(cap * 1.08))
                    if bump > plan.bitrate_kbps * 1.05:
                        if callback:
                            callback(
                                0.84,
                                f"体积 {file_size/1024:.1f}KB 偏低，上调码率 {plan.bitrate_kbps}k→{bump}k...",
                            )
                        plan = replace(plan, bitrate_kbps=bump)
                        filled = True
                        continue
                break

            file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            if file_size <= 0 or file_size > max_size:
                if callback:
                    callback(1.0, f"无法将体积压缩至 {max_limit_kb}KB 以内")
                return False

            if options.spoof_duration and not should_crop and real_duration > 3.0:
                if callback:
                    callback(0.95, "正在写入 EBML 头部时长信息 (2.99s)...")
                EBMLPatcher.patch_duration(output_path, target_seconds=2.99)

            if callback:
                final_kb = os.path.getsize(output_path) / 1024
                callback(1.0, f"转换完成，体积: {final_kb:.1f} KB | {plan.reason}")
            return True
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
