"""Загрузка конфигурации и XDG-пути.

Порядок приоритета (от слабого к сильному):
  значения по умолчанию → config.toml → переменные окружения → аргументы CLI.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "telega-cli"

IMAGE_PROTOCOLS = ("auto", "tgp", "sixel", "halfcell", "unicode", "none")
# selected — анимируется выделенное сообщение и полноэкранный просмотр;
# fullscreen — только полноэкранный просмотр (o); off — только первый кадр.
ANIMATION_MODES = ("selected", "fullscreen", "off")
# Цветовые темы, см. telega/ui/themes.py: пять тёмных и две светлые.
THEMES = ("cold", "warm", "vivid", "pastel", "matte", "light", "bright")


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback) / APP_NAME


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share")


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache")


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state")


class ConfigError(Exception):
    pass


@dataclass
class TelegramConfig:
    api_id: int | None = None
    api_hash: str | None = None
    session_name: str = "telega"


@dataclass
class UIConfig:
    # auto | tgp (kitty) | sixel (foot) | halfcell | unicode | none
    image_protocol: str = "auto"
    # Максимальная высота картинки в сообщении, в строках терминала.
    image_height: int = 12
    # Высота аватарки в окне профиля, в строках.
    avatar_height: int = 14
    # Высота стикера в ленте, в строках (GIF — как картинки, image_height).
    sticker_height: int = 8
    # Когда проигрывать GIF и анимированные стикеры (см. ANIMATION_MODES).
    animations: str = "selected"
    # В kitty отдавать кадры терминалу и пусть он анимирует сам (плавно, без
    # нагрузки на CPU). false — менять кадры из приложения, как в foot.
    kitty_native_animation: bool = True
    # Сколько сообщений загружать за один запрос истории.
    history_limit: int = 50
    # Показывать левую панель (список чатов). false — скрыта, выдвигается по h / Tab.
    show_chat_list: bool = True
    # Сколько диалогов загружать при старте.
    dialogs_limit: int = 100
    # Цветовая тема (см. THEMES). Меняется в приложении: Space t или :theme.
    theme: str = "cold"
    time_format: str = "%H:%M"
    date_format: str = "%d.%m.%Y"


@dataclass
class Config:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    # Файл конфига: откуда прочитан или куда будет сохранён.
    path: Path = field(default_factory=lambda: config_dir() / "config.toml")
    # Некритичные проблемы конфига (незнакомые параметры и т. п.): показываются
    # в статусной строке и пишутся в лог, но не мешают запуску.
    warnings: list[str] = field(default_factory=list)

    @property
    def has_api_credentials(self) -> bool:
        return bool(self.telegram.api_id and self.telegram.api_hash)

    @property
    def session_path(self) -> Path:
        return data_dir() / self.telegram.session_name

    @property
    def media_dir(self) -> Path:
        return cache_dir() / "media"

    @property
    def log_path(self) -> Path:
        return state_dir() / "telega.log"

    def require_api_credentials(self) -> tuple[int, str]:
        if not self.telegram.api_id or not self.telegram.api_hash:
            raise ConfigError(
                "Не заданы api_id / api_hash.\n"
                "Запустите telega — он покажет инструкцию и сохранит значения сам.\n"
                f"Или укажите их в {self.path} (секция [telegram]) либо в переменных\n"
                "окружения TELEGA_API_ID / TELEGA_API_HASH."
            )
        return self.telegram.api_id, self.telegram.api_hash


def _apply_section(target: object, values: dict, section: str, warnings: list[str]) -> None:
    for key, value in values.items():
        if not hasattr(target, key):
            # Не ошибка: конфиг мог записать более новый telega (например, [ui].theme),
            # а запущен старый. Падать из-за этого нельзя.
            warnings.append(f"неизвестный параметр [{section}].{key} пропущен")
            continue
        expected = type(getattr(target, key))
        if getattr(target, key) is not None and not isinstance(value, expected):
            raise ConfigError(
                f"[{section}].{key}: ожидается {expected.__name__}, получено {type(value).__name__}"
            )
        setattr(target, key, value)


def load_config(path: Path | None = None) -> Config:
    config = Config()
    path = path or config.path
    config.path = path
    if path.exists():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: {exc}") from exc
        _apply_section(config.telegram, raw.get("telegram", {}), "telegram", config.warnings)
        _apply_section(config.ui, raw.get("ui", {}), "ui", config.warnings)

    if api_id := os.environ.get("TELEGA_API_ID"):
        try:
            config.telegram.api_id = int(api_id)
        except ValueError as exc:
            raise ConfigError("TELEGA_API_ID должен быть числом") from exc
    if api_hash := os.environ.get("TELEGA_API_HASH"):
        config.telegram.api_hash = api_hash

    if config.ui.animations not in ANIMATION_MODES:
        raise ConfigError(f"[ui].animations: допустимо {', '.join(ANIMATION_MODES)}")
    if config.ui.theme not in THEMES:
        config.warnings.append(
            f"[ui].theme = {config.ui.theme!r} неизвестна, взята {UIConfig.theme!r}"
            f" (есть: {', '.join(THEMES)})"
        )
        config.ui.theme = UIConfig.theme
    if config.ui.image_protocol not in IMAGE_PROTOCOLS:
        raise ConfigError(
            f"[ui].image_protocol: допустимо {', '.join(IMAGE_PROTOCOLS)}"
        )
    return config


API_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def validate_api_credentials(api_id: str, api_hash: str) -> tuple[int, str]:
    """Проверить формат введённых значений. Бросает ConfigError с понятным текстом."""
    api_id, api_hash = api_id.strip(), api_hash.strip()
    if not api_id.isdigit() or not 0 < int(api_id) < 2**31:
        raise ConfigError("api_id — это число, например 1234567")
    if not API_HASH_RE.match(api_hash):
        raise ConfigError("api_hash — 32 символа 0-9 и a-f")
    return int(api_id), api_hash.lower()


_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(#.*)?$")


def _set_keys_in_section(text: str, section: str, values: dict[str, str]) -> str:
    """Записать `ключ = значение` в секцию TOML, сохранив остальной файл как есть.

    Значения передаются уже в TOML-виде (строки — в кавычках). Существующие
    ключи заменяются на месте, недостающие добавляются в конец секции; если
    секции нет — она дописывается в конец файла.
    """
    lines = text.splitlines()
    start = end = None
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m and start is None and m.group(1).strip() == section:
            start = i
        elif m and start is not None:
            end = i
            break
    if start is None:
        block = [f"[{section}]", *(f"{k} = {v}" for k, v in values.items())]
        if lines and lines[-1].strip():
            block.insert(0, "")
        return "\n".join(lines + block) + "\n"

    end = len(lines) if end is None else end
    pending = dict(values)
    for i in range(start + 1, end):
        key = lines[i].split("=", 1)[0].strip()
        if "=" in lines[i] and not lines[i].lstrip().startswith("#") and key in pending:
            lines[i] = f"{key} = {pending.pop(key)}"
    # Новые ключи — после последней непустой строки секции.
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines[insert_at:insert_at] = [f"{k} = {v}" for k, v in pending.items()]
    return "\n".join(lines) + "\n"


def _write_config(path: Path, text: str) -> None:
    tomllib.loads(text)  # не сохраняем то, что потом не прочитается
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def save_api_credentials(config: Config, api_id: int, api_hash: str) -> Path:
    """Сохранить api_id/api_hash в config.toml (права 600) и в сам `config`."""
    path = config.path
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    text = _set_keys_in_section(
        text, "telegram", {"api_id": str(api_id), "api_hash": f'"{api_hash}"'}
    )
    _write_config(path, text)
    config.telegram.api_id = api_id
    config.telegram.api_hash = api_hash
    return path


def save_theme(config: Config, theme: str) -> Path:
    """Запомнить тему в [ui].theme, не трогая остальной файл."""
    if theme not in THEMES:
        raise ConfigError(f"Неизвестная тема {theme!r}")
    path = config.path
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    _write_config(path, _set_keys_in_section(text, "ui", {"theme": f'"{theme}"'}))
    config.ui.theme = theme
    return path
