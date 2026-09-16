import json
import os
import subprocess
import zipfile
from datetime import datetime

from PIL import Image

from core.analyzer import MediaAnalyzer
from core.pack_output import STICKERS_JSON_NAME
from core.sticker_list import (
    BUNDLE_JSON_NAME,
    BUNDLE_SOURCES_DIR,
    LIST_KIND,
    build_sticker_list_document,
    default_bundle_name,
    default_list_name,
    export_prepared_stickers,
    prepared_output_ext,
    write_sticker_bundle,
    write_sticker_list,
)
from server.api import AppAPI


def test_default_list_name():
    name = default_list_name(datetime(2026, 9, 16, 12, 0, 0))
    assert name == "sticker_list_20260916_120000.json"


def test_default_bundle_name():
    name = default_bundle_name(datetime(2026, 9, 16, 12, 0, 0))
    assert name == "sticker_bundle_20260916_120000"


def test_build_skips_empty_path_and_keeps_clip_fields():
    doc = build_sticker_list_document(
        [
            {"input_path": "", "emoji": "x"},
            {
                "input_path": r"D:\a\clip.mp4",
                "file_name": "clip.mp4",
                "is_video": True,
                "emoji": "😀",
                "keywords": "cat,cute",
                "start_time": 1.25,
                "end_time": 3.5,
                "crop": [10, 20, 512, 512],
                "crop_radius": 0.5,
                "clip_group_id": "clipgrp-1",
                "clip_id": "clip-1",
                "clip_label": "[1.250s - 3.500s]",
            },
        ]
    )
    assert doc["kind"] == LIST_KIND
    assert doc["version"] == 1
    assert len(doc["stickers"]) == 1
    item = doc["stickers"][0]
    assert item["input_path"].endswith("clip.mp4")
    assert item["emoji"] == "😀"
    assert item["start_time"] == 1.25
    assert item["crop"] == [10, 20, 512, 512]
    assert item["clip_group_id"] == "clipgrp-1"
    assert doc["export_mode"] == "list"


def test_write_sticker_list(tmp_path):
    dest = tmp_path / "list.json"
    result = write_sticker_list(
        str(dest),
        [{"input_path": str(tmp_path / "a.mp4"), "emoji": "🎉", "keywords": "party"}],
    )
    assert result["count"] == 1
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["stickers"][0]["emoji"] == "🎉"


def test_write_sticker_bundle_copies_unique_sources(tmp_path):
    src_a = tmp_path / "a.mp4"
    src_b = tmp_path / "b.png"
    src_a.write_bytes(b"video-a")
    src_b.write_bytes(b"image-b")
    dest = tmp_path / "bundle"
    result = write_sticker_bundle(
        str(dest),
        [
            {"input_path": str(src_a), "emoji": "1️⃣", "start_time": 0, "end_time": 2},
            {"input_path": str(src_a), "emoji": "2️⃣", "start_time": 2, "end_time": 4},
            {"input_path": str(src_b), "emoji": "3️⃣"},
        ],
    )
    assert result["count"] == 3
    assert result["copied"] == 2
    assert (dest / BUNDLE_SOURCES_DIR / "a.mp4").read_bytes() == b"video-a"
    assert (dest / BUNDLE_SOURCES_DIR / "b.png").read_bytes() == b"image-b"
    data = json.loads((dest / BUNDLE_JSON_NAME).read_text(encoding="utf-8"))
    assert data["export_mode"] == "sources"
    assert data["stickers"][0]["input_path"] == f"{BUNDLE_SOURCES_DIR}/a.mp4"
    assert data["stickers"][1]["input_path"] == f"{BUNDLE_SOURCES_DIR}/a.mp4"
    assert data["stickers"][2]["input_path"] == f"{BUNDLE_SOURCES_DIR}/b.png"


def test_prepared_output_ext_keeps_source_video_container():
    assert prepared_output_ext(r"D:\a\clip.mkv", is_video=True, crop=None, radius=0) == ".mkv"
    assert prepared_output_ext(r"D:\a\clip.mkv", is_video=True, crop=[0, 0, 100, 100], radius=0) == ".mkv"
    assert prepared_output_ext(r"D:\a\clip.mkv", is_video=True, crop=[0, 0, 100, 100], radius=1) == ".mkv"
    assert prepared_output_ext(r"D:\a\clip.mp4", is_video=True, crop=[0, 0, 100, 100], radius=0) == ".mp4"


def test_export_prepared_copies_image_with_convert_name(tmp_path):
    src = tmp_path / "photo.png"
    src.write_bytes(b"png-bytes")
    dest = tmp_path / "out"
    result = export_prepared_stickers(
        [{"input_path": str(src), "emoji": "🐱", "is_video": False, "index": 1, "keywords": "cat"}],
        str(dest),
    )
    assert result["count"] == 1
    out = dest / "001_🐱.png"
    assert out.read_bytes() == b"png-bytes"


def test_export_prepared_zip_includes_manifest(tmp_path):
    src = tmp_path / "photo.png"
    src.write_bytes(b"png-bytes")
    dest = tmp_path / "stage"
    zpath = tmp_path / "pack.zip"
    export_prepared_stickers(
        [{"input_path": str(src), "emoji": "🐱", "is_video": False, "index": 2}],
        str(dest),
        zip_path=str(zpath),
    )
    with zipfile.ZipFile(zpath) as zf:
        names = zf.namelist()
        assert "002_🐱.png" in names
        assert STICKERS_JSON_NAME in names
        manifest = json.loads(zf.read(STICKERS_JSON_NAME))
        assert manifest["stickers"][0]["emoji"] == "🐱"


def test_export_prepared_stream_copy_clip(tmp_path):
    src = str(tmp_path / "sample_10s.mp4")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=10:size=320x240:rate=24",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            src,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    dest = tmp_path / "clips"
    result = export_prepared_stickers(
        [
            {
                "input_path": src,
                "emoji": "🎬",
                "is_video": True,
                "index": 1,
                "start_time": 3.0,
                "end_time": 5.5,
                "duration": 10,
            }
        ],
        str(dest),
    )
    assert result["count"] == 1
    out = dest / "001_🎬.mp4"
    assert out.is_file()
    assert out.stat().st_size > 512
    assert out.stat().st_size < os.path.getsize(src)


def test_export_prepared_applies_image_crop(tmp_path):
    src = tmp_path / "full.png"
    img = Image.new("RGB", (100, 80), (255, 0, 0))
    img.paste((0, 255, 0), (20, 10, 60, 40))
    img.save(src)
    dest = tmp_path / "out"
    export_prepared_stickers(
        [
            {
                "input_path": str(src),
                "emoji": "✂️",
                "is_video": False,
                "index": 1,
                "crop": [20, 10, 40, 30],
            }
        ],
        str(dest),
    )
    out = Image.open(dest / "001_✂️.png")
    assert out.size == (40, 30)
    assert out.getpixel((2, 2)) == (0, 255, 0)


def test_export_prepared_applies_video_crop(tmp_path):
    src = str(tmp_path / "sample.mp4")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=24",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            src,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    dest = tmp_path / "out"
    export_prepared_stickers(
        [
            {
                "input_path": src,
                "emoji": "🎬",
                "is_video": True,
                "index": 1,
                "start_time": 0,
                "end_time": 2,
                "duration": 2,
                "crop": [32, 16, 160, 120],
            }
        ],
        str(dest),
    )
    out = dest / "001_🎬.mp4"
    assert out.is_file()
    info = MediaAnalyzer.analyze(str(out))
    assert info.width == 160
    assert info.height == 120


def test_api_export_sticker_list_to_path(tmp_path):
    src = tmp_path / "b.png"
    src.write_bytes(b"img")
    dest = tmp_path / "out"
    api = AppAPI()
    res = api.export_sticker_list(
        [{"input_path": str(src), "emoji": "🐱", "is_video": False, "index": 1}],
        dest_path=str(dest),
        mode="list",
        global_options={"pack_output": False},
    )
    assert res["status"] == "ok"
    assert res["count"] == 1
    assert (dest / "001_🐱.png").is_file()


def test_api_export_sources_bundle(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"src")
    dest = tmp_path / "out_bundle"
    api = AppAPI()
    res = api.export_sticker_list(
        [{"input_path": str(src), "emoji": "🐱", "start_time": 1, "end_time": 2}],
        dest_path=str(dest),
        mode="sources",
    )
    assert res["status"] == "ok"
    assert res["copied"] == 1
    assert (dest / BUNDLE_JSON_NAME).is_file()
    assert (dest / BUNDLE_SOURCES_DIR / "clip.mp4").is_file()
