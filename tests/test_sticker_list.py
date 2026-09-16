import json
from datetime import datetime

from core.sticker_list import (
    BUNDLE_JSON_NAME,
    BUNDLE_SOURCES_DIR,
    LIST_KIND,
    build_sticker_list_document,
    default_bundle_name,
    default_list_name,
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


def test_api_export_sticker_list_to_path(tmp_path):
    api = AppAPI()
    dest = tmp_path / "out.json"
    res = api.export_sticker_list(
        [{"input_path": str(tmp_path / "b.webm"), "emoji": "🐱"}],
        dest_path=str(dest),
    )
    assert res["status"] == "ok"
    assert res["count"] == 1
    assert dest.is_file()


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
