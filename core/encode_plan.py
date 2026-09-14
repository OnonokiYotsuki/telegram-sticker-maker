"""Bitrate / fps planner for Telegram video stickers.

Pure functions: no ffmpeg, no I/O. Motion score is injected by the encoder.
`motion_score` is mean |Δ luma| / 255 on a 160x90 8fps probe:

- 0.00 still
- ~0.008 small motion
- ~0.018 full-body dance (TAK reference)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from core.analyzer import MediaInfo
from core.crop_shape import build_radius_mask_filter, radius_needs_alpha


STICKER_PAYLOAD_BYTES = 252 * 1024
EMOJI_PAYLOAD_BYTES = 60 * 1024
MIN_BPP = 0.055
EXTREME_BPP = 0.040
CQ_MAX_DURATION = 4.0
CQ_MIN_BPP = 0.10
MAX_FPS = 30.0
HARD_FLOOR_FPS = 15
EMERGENCY_FPS = 12
FPS_STEPS = (30, 24, 20, 18, 15)
MOTION_LOW = 0.007
MOTION_MED = 0.014
MAX_BITRATE_KBPS = 2000
MIN_BITRATE_KBPS = 16


class PlanOptions(Protocol):
    preset_style: str
    optimize_fps: bool
    custom_fps: Optional[int]
    is_custom_emoji: bool
    crf: Optional[int]
    crop_to_3s: bool
    start_time: Optional[float]
    end_time: Optional[float]
    crop: Optional[tuple[int, int, int, int]]
    crop_radius: float


@dataclass
class VideoEncodePlan:
    long_edge: int
    out_w: int
    out_h: int
    fps: float
    source_fps: float
    duration: float
    bitrate_kbps: int
    crf: Optional[int]
    two_pass: bool
    pix_fmt: str
    vf: str
    gop: int
    cpu_used_pass1: int
    cpu_used_pass2: int
    deadline: str
    auto_alt_ref: int
    payload_bytes: int
    reason: str


def align16(value: float) -> int:
    n = int(round(value / 16.0)) * 16
    return max(16, n)


def output_dims(src_w: int, src_h: int, long_edge: int) -> tuple[int, int]:
    src_w = max(1, src_w)
    src_h = max(1, src_h)
    if src_w >= src_h:
        short = min(long_edge, align16(long_edge * src_h / src_w))
        return long_edge, short
    short = min(long_edge, align16(long_edge * src_w / src_h))
    return short, long_edge


def cap_source_fps(src_fps: float) -> float:
    if src_fps <= 1:
        return 24.0
    return min(src_fps, MAX_FPS)


def bits_per_pixel(payload_bytes: int, duration: float, width: int, height: int, fps: float) -> float:
    denom = max(duration, 0.05) * max(width, 2) * max(height, 2) * max(fps, 1.0)
    return (payload_bytes * 8) / denom


def choose_bitrate_kbps(payload_bytes: int, duration: float) -> int:
    kbps = int(payload_bytes * 8 / max(duration, 0.05) / 1000)
    return max(MIN_BITRATE_KBPS, min(MAX_BITRATE_KBPS, kbps))


def lower_fps(current: float) -> Optional[int]:
    below = [step for step in (*FPS_STEPS, EMERGENCY_FPS) if step < current - 0.1]
    return max(below) if below else None


def _snap_source_fps(src_fps: float) -> float:
    """Keep native low GIF rates; snap 29.97/23.976 to 30/24."""
    capped = cap_source_fps(src_fps)
    if capped >= 28:
        return min(capped, 30.0)
    if capped >= 23:
        return min(capped, 24.0)
    return max(1.0, round(capped, 2))


def _fps_candidates(source_fps: float) -> list[float]:
    snapped = _snap_source_fps(source_fps)
    steps = [float(step) for step in FPS_STEPS if step <= snapped + 0.05]
    if snapped < HARD_FLOOR_FPS and snapped not in steps:
        steps.append(snapped)
    if snapped not in steps and snapped <= MAX_FPS:
        steps.append(snapped)
    steps = sorted(set(steps), reverse=True)
    return steps or [snapped]


def choose_fps(
    source_fps: float,
    duration: float,
    width: int,
    height: int,
    payload_bytes: int,
    *,
    optimize_fps: bool,
    custom_fps: Optional[int] = None,
    motion_score: Optional[float] = None,
) -> float:
    src = cap_source_fps(source_fps)
    if custom_fps:
        return max(1.0, min(float(custom_fps), src))
    if not optimize_fps:
        return _snap_source_fps(src)

    candidates = _fps_candidates(src)
    base = candidates[-1]
    for fps in candidates:
        if fps < HARD_FLOOR_FPS - 0.01 and src >= HARD_FLOOR_FPS:
            continue
        if bits_per_pixel(payload_bytes, duration, width, height, fps) >= MIN_BPP:
            base = fps
            break
    else:
        floor_ok = [f for f in candidates if f >= HARD_FLOOR_FPS - 0.01]
        base = min(floor_ok) if floor_ok else candidates[-1]

    if (
        src >= HARD_FLOOR_FPS
        and bits_per_pixel(payload_bytes, duration, width, height, max(base, HARD_FLOOR_FPS))
        < EXTREME_BPP
    ):
        base = float(EMERGENCY_FPS) if src >= EMERGENCY_FPS else base

    if motion_score is None:
        return base
    if motion_score < MOTION_LOW:
        return _snap_source_fps(src)
    if motion_score < MOTION_MED:
        higher = [f for f in candidates if f > base + 0.1]
        return min(higher) if higher else base
    return base


def _default_crf(preset_style: str, is_emoji: bool) -> int:
    if preset_style == "anime":
        return 22 if is_emoji else 15
    if preset_style == "cinema":
        return 24 if is_emoji else 18
    return 26 if is_emoji else 20


def build_vf(
    *,
    is_emoji: bool,
    preset_style: str,
    fps: float,
    source_fps: float,
    crop: Optional[tuple[int, int, int, int]] = None,
    crop_radius: float = 0.0,
) -> str:
    flags = "lanczos+accurate_rnd+full_chroma_int"
    filters = []
    if crop is not None:
        cx, cy, cw, ch = crop
        cw = max(2, cw - (cw % 2))
        ch = max(2, ch - (ch % 2))
        cx = max(0, cx - (cx % 2))
        cy = max(0, cy - (cy % 2))
        filters.append(f"crop={cw}:{ch}:{cx}:{cy}")

    if is_emoji:
        filters.extend([
            f"scale='if(gte(iw,ih),100,-2)':'if(gte(iw,ih),-2,100)':flags={flags}",
            "pad=100:100:(100-iw)/2:(100-ih)/2:color=black@0",
        ])
    else:
        filters.append(
            f"scale='if(gte(iw,ih),512,-16)':'if(gte(iw,ih),-16,512)':flags={flags}"
        )

    if preset_style == "anime":
        filters.append("unsharp=5:5:0.35:5:5:0.0")
    elif preset_style == "cinema":
        filters.append("hqdn3d=1.0:1.0:2:2")

    if abs(fps - source_fps) >= 0.6:
        filters.append(f"fps={fps:g}")

    mask = build_radius_mask_filter(crop_radius)
    if mask:
        filters.append(mask)

    return ",".join(filters)


def plan_video(
    info: MediaInfo,
    options: PlanOptions,
    motion_score: Optional[float] = None,
) -> VideoEncodePlan:
    is_emoji = options.is_custom_emoji
    long_edge = 100 if is_emoji else 512
    start_time = getattr(options, "start_time", None)
    end_time = getattr(options, "end_time", None)
    if start_time is not None and end_time is not None and end_time > start_time:
        duration = end_time - start_time
    else:
        duration = info.duration if info.duration > 0.05 else 3.0
    if options.crop_to_3s and duration > 3.0:
        duration = 3.0

    crop = getattr(options, "crop", None)
    if crop is not None:
        _, _, cw, ch = crop
        src_w = max(16, cw - (cw % 2))
        src_h = max(16, ch - (ch % 2))
    else:
        src_w = info.width
        src_h = info.height

    if is_emoji:
        out_w, out_h = 100, 100
    else:
        out_w, out_h = output_dims(src_w, src_h, long_edge)

    payload = EMOJI_PAYLOAD_BYTES if is_emoji else STICKER_PAYLOAD_BYTES
    source_fps = cap_source_fps(info.fps)
    fps = choose_fps(
        info.fps,
        duration,
        out_w,
        out_h,
        payload,
        optimize_fps=options.optimize_fps,
        custom_fps=options.custom_fps,
        motion_score=motion_score,
    )
    bitrate_kbps = choose_bitrate_kbps(payload, duration)
    bpp = bits_per_pixel(payload, duration, out_w, out_h, fps)
    use_cq = duration <= CQ_MAX_DURATION and bpp >= CQ_MIN_BPP
    preset = options.preset_style or "anime"
    crf = None
    if use_cq:
        crf = options.crf if options.crf is not None else _default_crf(preset, is_emoji)

    two_pass = preset != "fast"
    if two_pass:
        cpu1, cpu2, deadline = 4, 1, "good"
    else:
        cpu1, cpu2, deadline = 4, 4, "good"

    crop_radius = float(getattr(options, "crop_radius", 0.0) or 0.0)
    has_alpha = info.has_alpha or radius_needs_alpha(crop_radius)
    pix_fmt = "yuva420p" if has_alpha else "yuv420p"
    auto_alt_ref = 0 if has_alpha else 1

    vf = build_vf(
        is_emoji=is_emoji,
        preset_style=preset,
        fps=fps,
        source_fps=source_fps,
        crop=crop,
        crop_radius=crop_radius,
    )

    motion_tag = "未测运动"
    if motion_score is not None:
        if motion_score < MOTION_LOW:
            motion_tag = f"低运动 {motion_score:.3f}"
        elif motion_score < MOTION_MED:
            motion_tag = f"中运动 {motion_score:.3f}"
        else:
            motion_tag = f"高运动 {motion_score:.3f}"

    mode = "CQ" if use_cq else "ABR"
    fps_note = f"{source_fps:g}→{fps:g}fps" if abs(fps - source_fps) >= 0.6 else f"{fps:g}fps"
    reason = (
        f"{duration:.1f}s {out_w}x{out_h} {fps_note} | {motion_tag} | "
        f"{mode} {bitrate_kbps}kbps bpp={bpp:.3f}"
    )

    return VideoEncodePlan(
        long_edge=long_edge,
        out_w=out_w,
        out_h=out_h,
        fps=fps,
        source_fps=source_fps,
        duration=duration,
        bitrate_kbps=bitrate_kbps,
        crf=crf,
        two_pass=two_pass,
        pix_fmt=pix_fmt,
        vf=vf,
        gop=9999,
        cpu_used_pass1=cpu1,
        cpu_used_pass2=cpu2,
        deadline=deadline,
        auto_alt_ref=auto_alt_ref,
        payload_bytes=payload,
        reason=reason,
    )
