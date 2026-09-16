import json
from PIL import Image

from core.session_store import load_session, save_session
from server.api import AppAPI


def _png(path):
    Image.new("RGBA", (32, 32), (10, 20, 30, 255)).save(path)


def test_save_and_load_roundtrip(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")
    session = tmp_path / "session.json"
    result = save_session(
        [
            {
                "input_path": str(src),
                "file_name": "clip.mp4",
                "is_video": True,
                "emoji": "😀",
                "keywords": "cat, cute",
                "start_time": 1.25,
                "end_time": 3.5,
                "crop": [10, 20, 512, 512],
                "crop_radius": 0.5,
                "clip_group_id": "clipgrp-1",
                "clip_id": "clip-1",
                "clip_label": "[1.250s - 3.500s]",
            }
        ],
        path=str(session),
    )
    assert result["count"] == 1
    assert session.is_file()

    loaded = load_session(path=str(session))
    assert loaded["status"] == "ok"
    assert loaded["count"] == 1
    assert loaded["missing"] == []
    item = loaded["stickers"][0]
    assert item["input_path"] == str(src)
    assert item["emoji"] == "😀"
    assert item["keywords"] == "cat, cute"
    assert item["start_time"] == 1.25
    assert item["end_time"] == 3.5
    assert item["crop"] == [10, 20, 512, 512]
    assert item["crop_radius"] == 0.5
    assert item["clip_group_id"] == "clipgrp-1"


def test_save_empty_session(tmp_path):
    session = tmp_path / "session.json"
    result = save_session([], path=str(session))
    assert result["count"] == 0
    loaded = load_session(path=str(session))
    assert loaded["status"] == "empty"
    assert loaded["stickers"] == []


def test_load_missing_file_is_empty(tmp_path):
    loaded = load_session(path=str(tmp_path / "nope.json"))
    assert loaded["status"] == "empty"
    assert loaded["count"] == 0


def test_load_skips_missing_sources(tmp_path):
    gone = tmp_path / "gone.png"
    keep = tmp_path / "keep.png"
    _png(keep)
    session = tmp_path / "session.json"
    save_session(
        [
            {"input_path": str(gone), "emoji": "x", "is_video": False},
            {"input_path": str(keep), "emoji": "y", "is_video": False},
        ],
        path=str(session),
    )
    loaded = load_session(path=str(session))
    assert loaded["status"] == "ok"
    assert loaded["count"] == 1
    assert loaded["stickers"][0]["input_path"] == str(keep)
    assert loaded["missing"] == [str(gone)]


def test_load_corrupt_json_is_empty(tmp_path):
    session = tmp_path / "session.json"
    session.write_text("{not json", encoding="utf-8")
    loaded = load_session(path=str(session))
    assert loaded["status"] == "empty"


def test_api_save_and_load_session(tmp_path, monkeypatch):
    session = tmp_path / "session.json"
    monkeypatch.setattr("core.session_store.session_path", lambda: str(session))
    src = tmp_path / "a.png"
    _png(src)
    api = AppAPI()
    saved = api.save_session(
        [{"input_path": str(src), "emoji": "🐱", "is_video": False, "keywords": "cat"}]
    )
    assert saved["status"] == "ok"
    assert json.loads(session.read_text(encoding="utf-8"))["stickers"][0]["emoji"] == "🐱"

    loaded = api.load_session()
    assert loaded["status"] == "ok"
    assert loaded["count"] == 1
    assert loaded["stickers"][0]["emoji"] == "🐱"


def test_api_flush_skips_until_first_save(tmp_path, monkeypatch):
    session = tmp_path / "session.json"
    monkeypatch.setattr("core.session_store.session_path", lambda: str(session))
    api = AppAPI()
    flushed = api.flush_session()
    assert flushed["status"] == "skipped"
    assert not session.exists()

    src = tmp_path / "a.png"
    _png(src)
    api.save_session([{"input_path": str(src), "is_video": False}])
    api._session_stickers = [{"input_path": str(src), "emoji": "x", "is_video": False}]
    flushed = api.flush_session()
    assert flushed["status"] == "ok"
    loaded = api.load_session()
    assert loaded["stickers"][0]["emoji"] == "x"
