import json
from datetime import datetime

from core.sticker_list import (
    LIST_KIND,
    build_sticker_list_document,
    default_list_name,
    write_sticker_list,
)
from server.api import AppAPI


def test_default_list_name():
    name = default_list_name(datetime(2026, 9, 16, 12, 0, 0))
    assert name == "sticker_list_20260916_120000.json"


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


def test_write_sticker_list(tmp_path):
    dest = tmp_path / "list.json"
    result = write_sticker_list(
        str(dest),
        [{"input_path": str(tmp_path / "a.mp4"), "emoji": "🎉", "keywords": "party"}],
    )
    assert result["count"] == 1
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["stickers"][0]["emoji"] == "🎉"


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
