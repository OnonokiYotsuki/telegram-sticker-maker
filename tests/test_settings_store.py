from core.settings_store import load_settings, save_settings


def test_clip_dialog_crop_defaults_roundtrip(tmp_path, monkeypatch):
    ini = tmp_path / "settings.ini"
    monkeypatch.setattr("core.settings_store.settings_path", lambda: str(ini))
    save_settings(
        {
            "small_step_sec": 0.25,
            "large_step_sec": 10,
            "default_crop_aspect": "16:9",
            "default_crop_radius": 0.5,
            "show_timeline_overview": False,
        }
    )
    loaded = load_settings()
    assert loaded["small_step_sec"] == 0.25
    assert loaded["large_step_sec"] == 10
    assert loaded["default_crop_aspect"] == "16:9"
    assert loaded["default_crop_radius"] == 0.5
    assert loaded["show_timeline_overview"] is False


def test_clip_dialog_rejects_invalid_aspect(tmp_path, monkeypatch):
    ini = tmp_path / "settings.ini"
    monkeypatch.setattr("core.settings_store.settings_path", lambda: str(ini))
    save_settings({"default_crop_aspect": "nope", "default_crop_radius": 2.5})
    loaded = load_settings()
    assert loaded["default_crop_aspect"] == "1:1"
    assert loaded["default_crop_radius"] == 1.0
