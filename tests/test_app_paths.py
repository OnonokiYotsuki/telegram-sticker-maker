import os

from core.app_paths import (
    apply_data_dir_change,
    data_dir,
    import_dir,
    proxy_dir,
    session_file,
    set_config_dir_override,
    set_data_dir_override,
)


def test_default_layout_under_config_dir(tmp_path):
    cfg = tmp_path / "cfg"
    set_config_dir_override(str(cfg))
    set_data_dir_override(None)
    try:
        root = data_dir()
        assert os.path.normcase(root) == os.path.normcase(str(cfg))
        assert os.path.isdir(proxy_dir())
        assert os.path.isdir(import_dir())
        assert session_file() == os.path.join(root, "session.json")
        assert os.path.basename(proxy_dir()) == "proxies"
        assert os.path.basename(import_dir()) == "imports"
    finally:
        set_config_dir_override(None)
        set_data_dir_override(None)


def test_custom_data_dir_from_ini(tmp_path):
    cfg = tmp_path / "cfg"
    data = tmp_path / "work"
    cfg.mkdir()
    (cfg / "settings.ini").write_text(
        f"[settings]\ndata_dir = {data}\n",
        encoding="utf-8",
    )
    set_config_dir_override(str(cfg))
    set_data_dir_override(None)
    try:
        root = data_dir()
        assert os.path.normcase(root) == os.path.normcase(str(data))
        assert (data / "proxies").is_dir()
        assert (data / "imports").is_dir()
        assert session_file() == str(data / "session.json")
    finally:
        set_config_dir_override(None)
        set_data_dir_override(None)


def test_apply_data_dir_change_copies_session(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    (old / "session.json").write_text("{}", encoding="utf-8")
    set_data_dir_override(str(new))
    try:
        apply_data_dir_change(str(old))
        assert (new / "session.json").is_file()
        assert (new / "proxies").is_dir()
    finally:
        set_data_dir_override(None)
