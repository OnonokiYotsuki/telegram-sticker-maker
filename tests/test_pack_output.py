import os
import zipfile
from datetime import datetime

import pytest

from core.pack_output import (
    PackEntry,
    PackError,
    default_zip_name,
    pack_stickers,
    unique_arcname,
)
from server.api import AppAPI


def _touch(path: str, data: bytes = b"sticker") -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def test_default_zip_name():
    name = default_zip_name(datetime(2026, 9, 14, 15, 30, 45))
    assert name == "TG_Stickers_20260914_153045.zip"


def test_unique_arcname_collision():
    used: set[str] = set()
    assert unique_arcname("001_😂.webm", used) == "001_😂.webm"
    assert unique_arcname("001_😂.webm", used) == "001_😂_2.webm"
    assert unique_arcname("001_😂.webm", used) == "001_😂_3.webm"


def test_pack_stickers_only_contains_stickers(tmp_path):
    a = _touch(str(tmp_path / "001_😂.webm"), b"webm-a")
    b = _touch(str(tmp_path / "002.webp"), b"webp-b")
    zip_path = str(tmp_path / "pack" / "out.zip")

    result = pack_stickers(
        [PackEntry(path=a, emoji="😂"), PackEntry(path=b, emoji="🥺")],
        zip_path,
    )
    assert result["count"] == 2
    assert os.path.isfile(zip_path)
    assert result["bytes"] == os.path.getsize(zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        assert set(zf.namelist()) == {"001_😂.webm", "002.webp"}
        assert zf.read("001_😂.webm") == b"webm-a"
        assert zf.read("002.webp") == b"webp-b"


def test_pack_skips_missing_and_rejects_empty(tmp_path):
    missing = str(tmp_path / "gone.webm")
    with pytest.raises(PackError):
        pack_stickers([PackEntry(path=missing, emoji="x")], str(tmp_path / "empty.zip"))


def test_api_pack_outputs(tmp_path):
    api = AppAPI()
    f1 = _touch(str(tmp_path / "src" / "001_😀.webm"))
    dest = str(tmp_path / "out" / "stickers.zip")
    res = api.pack_outputs(
        [{"path": f1, "emoji": "😀"}],
        zip_path=dest,
        is_custom_emoji=True,
    )
    assert res["status"] == "ok"
    assert res["count"] == 1
    assert os.path.isfile(dest)
    with zipfile.ZipFile(dest) as zf:
        assert zf.namelist() == ["001_😀.webm"]


def test_conversion_packs_when_enabled(monkeypatch, tmp_path):
    api = AppAPI()
    monkeypatch.setattr(api, "_eval_js", lambda _s: None)
    monkeypatch.setattr(api, "_log", lambda _m: None)

    def fake_convert(input_path, output_path, options=None, progress_callback=None):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as fh:
            fh.write(b"webm")
        return True

    monkeypatch.setattr("server.api.StickerEncoder.convert", fake_convert)

    out_dir = tmp_path / "out"
    tasks = [
        {
            "task_id": 1,
            "input_path": str(tmp_path / "in1.mp4"),
            "output_path": str(out_dir / "001_😂.webm"),
            "emoji": "😂",
        },
        {
            "task_id": 2,
            "input_path": str(tmp_path / "in2.mp4"),
            "output_path": str(out_dir / "002_🥺.webm"),
            "emoji": "🥺",
        },
    ]
    api._run_conversion_worker(
        tasks,
        {
            "pack_output": True,
            "custom_output_dir": str(out_dir),
            "is_custom_emoji": False,
        },
    )
    zips = list(out_dir.glob("TG_Stickers_*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        assert set(zf.namelist()) == {"001_😂.webm", "002_🥺.webm"}
    assert not (out_dir / "001_😂.webm").exists()
    assert not (out_dir / "002_🥺.webm").exists()
    assert list(out_dir.glob("*.webm")) == []


def test_conversion_skips_pack_when_disabled(monkeypatch, tmp_path):
    api = AppAPI()
    monkeypatch.setattr(api, "_eval_js", lambda _s: None)
    monkeypatch.setattr(api, "_log", lambda _m: None)

    def fake_convert(input_path, output_path, options=None, progress_callback=None):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as fh:
            fh.write(b"webm")
        return True

    monkeypatch.setattr("server.api.StickerEncoder.convert", fake_convert)
    out_dir = tmp_path / "out"
    tasks = [
        {
            "task_id": 1,
            "input_path": str(tmp_path / "in.mp4"),
            "output_path": str(out_dir / "001.webm"),
        }
    ]
    api._run_conversion_worker(
        tasks,
        {"pack_output": False, "custom_output_dir": str(out_dir)},
    )
    assert list(out_dir.glob("*.zip")) == []
    assert os.path.isfile(tasks[0]["output_path"])
