"""Rounded-rect crop mask for Telegram stickers.

`crop_radius` is 0..1 of the maximum corner radius (half the short side):
0 = sharp rectangle, 1 = circle (square crop) or stadium/pill (non-square).
"""
from __future__ import annotations

from typing import Optional, Union

from PIL import Image, ImageChops, ImageDraw

RadiusValue = Union[float, int, str, None]
RADIUS_EPS = 0.001


def normalize_crop_radius(value: RadiusValue) -> float:
    if value is None or value == "":
        return 0.0
    try:
        radius = float(value)
    except (TypeError, ValueError):
        return 0.0
    if radius != radius:  # NaN
        return 0.0
    return max(0.0, min(1.0, radius))


def radius_needs_alpha(value: RadiusValue) -> bool:
    return normalize_crop_radius(value) > RADIUS_EPS


def crop_radius_label(value: RadiusValue) -> str:
    radius = normalize_crop_radius(value)
    if radius <= RADIUS_EPS:
        return "直角"
    if radius >= 1.0 - RADIUS_EPS:
        return "圆形"
    return f"圆角 {int(round(radius * 100))}%"


def _esc_geq(expr: str) -> str:
    """Escape commas so a geq expression can live inside a -vf chain."""
    return expr.replace(",", "\\,")


def build_radius_mask_filter(value: RadiusValue) -> str:
    """FFmpeg filter fragment applied after scale. Empty when radius is 0."""
    radius = normalize_crop_radius(value)
    if radius <= RADIUS_EPS:
        return ""
    r = f"min(W,H)*0.5*{radius:.4f}"
    expr = (
        f"if(gt("
        f"between(X,{r},W-({r}))*between(Y,0,H)"
        f"+between(Y,{r},H-({r}))*between(X,0,W)"
        f"+lte(hypot(X-({r}),Y-({r})),{r})"
        f"+lte(hypot(X-(W-({r})),Y-({r})),{r})"
        f"+lte(hypot(X-({r}),Y-(H-({r}))),{r})"
        f"+lte(hypot(X-(W-({r})),Y-(H-({r}))),{r})"
        f",0),alpha(X,Y),0)"
    )
    return (
        "format=rgba,"
        f"geq=r='{_esc_geq('r(X,Y)')}':"
        f"g='{_esc_geq('g(X,Y)')}':"
        f"b='{_esc_geq('b(X,Y)')}':"
        f"a='{_esc_geq(expr)}'"
    )


def apply_crop_radius(image: Image.Image, value: RadiusValue) -> Image.Image:
    """Apply a rounded-rect alpha mask. Returns an RGBA image."""
    radius = normalize_crop_radius(value)
    img = image.convert("RGBA")
    if radius <= RADIUS_EPS:
        return img

    w, h = img.size
    if w < 2 or h < 2:
        return img

    px_radius = max(1, int(round(min(w, h) * 0.5 * radius)))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, w - 1, h - 1),
        radius=px_radius,
        fill=255,
    )
    alpha = img.split()[-1]
    img.putalpha(ImageChops.multiply(alpha, mask))
    return img
