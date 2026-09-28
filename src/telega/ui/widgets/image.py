"""Отрисовка картинок в терминале (kitty graphics protocol / sixel).

textual-image определяет возможности терминала запросами в stdin/stdout,
а это возможно только ДО запуска Textual. Поэтому `init_images()` вызывается
в `__main__` до `app.run()`, а виджеты создаются через `make_image()`.

Протоколы:
  tgp      — Terminal Graphics Protocol (kitty, ghostty)
  sixel    — foot, wezterm, xterm, konsole
  halfcell — цветные полублоки ▀ (работает везде, низкое качество)
  unicode  — псевдографика (работает везде)
  none     — не рисовать, показывать только подпись [фото]
  auto     — выбор textual-image (sixel → tgp → halfcell)
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image as PILImage
from textual.widget import Widget
from textual.widgets import Static

log = logging.getLogger(__name__)

_image_cls: type[Widget] | None = None
_protocol_name = "none"


def init_images(protocol: str) -> str:
    """Выбрать класс виджета картинок. Вызывать до запуска приложения.

    Возвращает фактически выбранный протокол (для статусной строки и логов).
    """
    global _image_cls, _protocol_name
    if protocol == "none":
        _image_cls, _protocol_name = None, "none"
        return _protocol_name
    try:
        # Импорт запускает определение возможностей терминала.
        from textual_image import renderable
        from textual_image import widget as ti
    except Exception:  # pragma: no cover - зависит от терминала
        log.exception("textual-image недоступен, картинки отключены")
        _image_cls, _protocol_name = None, "none"
        return _protocol_name

    classes = {
        "tgp": ti.TGPImage,
        "sixel": ti.SixelImage,
        "halfcell": ti.HalfcellImage,
        "unicode": ti.UnicodeImage,
    }
    if protocol == "auto":
        _image_cls = ti.Image
        detected = renderable.Image
        _protocol_name = {
            renderable.TGPImage: "tgp",
            renderable.SixelImage: "sixel",
            renderable.HalfcellImage: "halfcell",
            renderable.UnicodeImage: "unicode",
        }.get(detected, "auto")
    else:
        _image_cls = classes[protocol]
        _protocol_name = protocol
    log.info("Протокол картинок: %s", _protocol_name)
    return _protocol_name


def images_enabled() -> bool:
    return _image_cls is not None


def protocol_name() -> str:
    return _protocol_name


def make_image(
    source: Path | PILImage.Image, *, classes: str = "", fallback: str = "[картинка]"
) -> Widget:
    """Виджет картинки (из файла или PIL.Image) или текстовая заглушка,
    если картинки отключены/битые."""
    if _image_cls is None:
        return Static(fallback, classes=f"image-fallback {classes}")

    def on_error(exc: Exception) -> Widget:
        log.warning("Не удалось открыть %s: %s", source, exc)
        return Static(f"{fallback} (ошибка: {exc})", classes="image-fallback")

    return _image_cls(source, classes=classes, on_error=on_error)
