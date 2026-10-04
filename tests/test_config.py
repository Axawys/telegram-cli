import stat
import tomllib

import pytest

from telega.config import (
    Config,
    ConfigError,
    load_config,
    save_api_credentials,
    save_theme,
    validate_api_credentials,
)

HASH = "0123456789abcdef0123456789abcdef"


def test_validate_ok():
    assert validate_api_credentials(" 1234567 ", HASH.upper()) == (1234567, HASH)


@pytest.mark.parametrize(
    ("api_id", "api_hash", "field"),
    [("", HASH, "api_id"), ("12a", HASH, "api_id"), ("0", HASH, "api_id"),
     ("123", "abc", "api_hash"), ("123", "z" * 32, "api_hash")],
)
def test_validate_errors(api_id, api_hash, field):
    with pytest.raises(ConfigError, match=field):
        validate_api_credentials(api_id, api_hash)


def test_save_creates_file_with_600(tmp_path):
    config = Config(path=tmp_path / "sub" / "config.toml")
    save_api_credentials(config, 42, HASH)
    data = tomllib.loads(config.path.read_text())
    assert data["telegram"] == {"api_id": 42, "api_hash": HASH}
    assert stat.S_IMODE(config.path.stat().st_mode) == 0o600
    assert config.has_api_credentials


def test_save_keeps_other_sections_and_comments(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('# мой конфиг\n[ui]\nimage_height = 20  # побольше\n')
    config = load_config(path)
    save_api_credentials(config, 42, HASH)
    text = path.read_text()
    assert "# мой конфиг" in text and "# побольше" in text
    reloaded = load_config(path)
    assert reloaded.ui.image_height == 20
    assert reloaded.telegram.api_id == 42 and reloaded.telegram.api_hash == HASH


def test_save_replaces_existing_values_in_place(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[telegram]\napi_id = 1\nsession_name = "work"\napi_hash = "old"\n\n[ui]\nimage_height = 5\n')
    config = load_config(path)
    save_api_credentials(config, 42, HASH)
    data = tomllib.loads(path.read_text())
    assert data["telegram"] == {"api_id": 42, "session_name": "work", "api_hash": HASH}
    assert data["ui"] == {"image_height": 5}


def test_save_adds_missing_key_to_existing_section(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[telegram]\nsession_name = "work"\n\n[ui]\nimage_height = 5\n')
    config = load_config(path)
    save_api_credentials(config, 42, HASH)
    data = tomllib.loads(path.read_text())
    assert data["telegram"]["api_id"] == 42 and data["ui"] == {"image_height": 5}


def test_env_overrides_file(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(f'[telegram]\napi_id = 1\napi_hash = "{HASH}"\n')
    monkeypatch.setenv("TELEGA_API_ID", "777")
    assert load_config(path).telegram.api_id == 777


def test_save_theme_keeps_credentials(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[telegram]\napi_id = 1\napi_hash = "x"\n\n[ui]\nimage_height = 9\n')
    config = load_config(path)
    save_theme(config, "warm")
    raw = tomllib.loads(path.read_text())
    assert raw["ui"] == {"image_height": 9, "theme": "warm"}
    assert raw["telegram"]["api_id"] == 1
    assert load_config(path).ui.theme == "warm"


def test_unknown_theme_falls_back(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[ui]\ntheme = "neon"\n')
    config = load_config(path)
    assert config.ui.theme == "cold"
    assert any("neon" in w for w in config.warnings)
    with pytest.raises(ConfigError):
        save_theme(load_config(tmp_path / "none.toml"), "neon")


def test_unknown_key_is_warning_not_error(tmp_path):
    # Конфиг, записанный более новой версией, не должен ломать запуск старой.
    path = tmp_path / "config.toml"
    path.write_text('[ui]\nfuture_option = 1\nimage_height = 7\n\n[newsection]\nx = 1\n')
    config = load_config(path)
    assert config.ui.image_height == 7
    assert config.warnings == ["неизвестный параметр [ui].future_option пропущен"]
