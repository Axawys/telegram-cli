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


def _fixed_sixel_class() -> type[Widget]:
    """Sixel-виджет textual-image с исправлениями для foot.

    1. Хвост под картинкой. Sixel рисуется полосами по 6 пикселей. Кодировщик
       добивает последнюю неполную полосу чёрным (аватарка 2 строки × 25 px =
       50 px → 54) и ставит «-» (переход к следующей полосе) ещё и после
       последней — foot начинает по нему лишнюю полосу (+6 px). Хвост залезает
       на строку ниже и остаётся там при частичной перерисовке: аватарка в
       списке «вырастала» при смене выделения, под фото была полоска.
       Поэтому дополняем картинку до кратной 6 высоты ПРОЗРАЧНЫМИ строками
       (их кодировщик не рисует, а foot отбрасывает прозрачный хвост) и
       убираем завершающий «-». Обрезать саму картинку нельзя: на частичных
       перерисовках это оставляло стёртые полоски и давало мерцание.

    2. Курсор после картинки. textual-image возвращает его в (right, bottom),
       а bottom — строка ПОД картинкой. Textual же думает, что курсор на
       последней строке картинки: дописывает остаток строки на строку ниже и
       выводит перевод строки. У нижнего края экрана (просмотр фото) это
       прокручивает весь экран foot — пропадает верхняя рамка, нижняя двоится,
       после закрытия остаётся мусор: Textual о прокрутке не знает.

    3. Место частично перерисованной картинки. Если перерисовывается не вся
       картинка, а её кусок (crop), textual-image ставит этот кусок в левый
       верхний угол видимой области, а не туда, где он на самом деле.
       Ставим по координатам самого куска.

    `_ImageSixelImpl`, `_image_to_sixels`, `_get_sixel_segments` — внутренности
    textual-image; регрессию ловит test_sixel_output_matches_cells.
    """
    from rich.control import Control
    from rich.segment import ControlType, Segment
    from rich.style import Style
    from textual_image.widget.sixel import Image as SixelImage
    from textual_image.widget.sixel import _ImageSixelImpl, _NoopRenderable

    null_style = Style()
    st = "\x1b\\"

    class FixedSixelImpl(_ImageSixelImpl):
        _crop = None  # что перерисовываем сейчас (в координатах виджета)

        def render_lines(self, crop):
            self._crop = crop
            return super().render_lines(crop)

        def _image_to_sixels(self, image, sixel_options=None, background=None):
            if image.height % 6:  # правка 1: прозрачный добив до полной полосы
                padded = PILImage.new("RGBA", (image.width, image.height + 6 - image.height % 6))
                padded.paste(image.convert("RGBA"), (0, 0))
                image = padded
            data = super()._image_to_sixels(image, sixel_options, background)
            if data.endswith("-" + st):  # правка 1
                data = data[: -len(st) - 1] + st
            return data

        def _get_sixel_segments(self, sixel_data):
            region = self.screen.find_widget(self).region
            crop = self._crop or region.reset_offset
            x, y = region.x + crop.x, region.y + crop.y  # правка 3
            return [
                Segment(Control.move_to(x, y).segment.text, style=null_style),
                Segment(sixel_data, style=null_style, control=((ControlType.CURSOR_FORWARD, 0),)),
                # Конец последней строки куска, а не строка под ним (правка 2).
                Segment(Control.move_to(x + crop.width, y + crop.height - 1).segment.text,
                        style=null_style),
            ]

    class FixedSixelImage(SixelImage, Renderable=_NoopRenderable):
        def compose(self):
            yield FixedSixelImpl(self.image, self._sixel_options)

    return FixedSixelImage


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

    sixel_cls = _fixed_sixel_class()
    classes = {
        "tgp": ti.TGPImage,
        "sixel": sixel_cls,
        "halfcell": ti.HalfcellImage,
        "unicode": ti.UnicodeImage,
    }
    if protocol == "auto":
        _image_cls = sixel_cls if ti.Image is ti.SixelImage else ti.Image
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
