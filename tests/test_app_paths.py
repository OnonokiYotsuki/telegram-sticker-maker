import os

from core.app_paths import (
    DATA_FOLDER_NAME,
    apply_data_dir_change,
    data_dir,
    import_dir,
    proxy_dir,
    resolve_custom_data_dir,
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
        nested = data / DATA_FOLDER_NAME
        assert os.path.normcase(root) == os.path.normcase(str(nested))
        assert (nested / "proxies").is_dir()
        assert (nested / "imports").is_dir()
        assert session_file() == str(nested / "session.json")
    finally:
        set_config_dir_override(None)
        set_data_dir_override(None)


def test_resolve_custom_data_dir_nests_app_folder(tmp_path):
    parent = tmp_path / "2"
    parent.mkdir()
    nested = resolve_custom_data_dir(str(parent))
    assert os.path.basename(nested) == DATA_FOLDER_NAME
    assert os.path.normcase(os.path.dirname(nested)) == os.path.normcase(str(parent))


def test_resolve_custom_data_dir_does_not_double_nest(tmp_path):
    already = tmp_path / DATA_FOLDER_NAME
    already.mkdir()
    assert os.path.normcase(resolve_custom_data_dir(str(already))) == os.path.normcase(str(already))


def test_resolve_custom_data_dir_keeps_existing_root(tmp_path):
    old = tmp_path / "legacy"
    old.mkdir()
    (old / "session.json").write_text("{}", encoding="utf-8")
    assert os.path.normcase(resolve_custom_data_dir(str(old))) == os.path.normcase(str(old))


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
