import pytest

from core.app_paths import set_config_dir_override, set_data_dir_override


@pytest.fixture(autouse=True)
def isolate_app_paths(tmp_path_factory):
    root = tmp_path_factory.mktemp("app_paths")
    set_config_dir_override(str(root / "cfg"))
    set_data_dir_override(None)
    yield
    set_config_dir_override(None)
    set_data_dir_override(None)
