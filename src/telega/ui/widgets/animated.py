"""Виджет анимации (GIF, анимированные и видео-стикеры).

Два способа воспроизведения:

native (только kitty / TGP)
    Все кадры один раз передаются в терминал командами kitty graphics
    protocol (`a=f`), а проигрыванием управляет сам kitty (`a=a`). Клиент
    не тратит CPU, анимация плавная. Надстройка над textual-image:
    `_AnimatedTGPRenderable` досылает кадры сразу после базовой картинки.

swap (любой протокол: sixel, halfcell, unicode, а также TGP при
`kitty_native_animation = false`)
    Кадры меняются по таймеру через `image.image = кадр`. Для sixel каждый
    кадр кодируется заново (~15–20 мс на 200×200) и перерисовывается —
    возможны мерцание и нагрузка на CPU.

Состояние (играет / стоит) хранит `AnimationController`: textual-image
пересоздаёт renderable при каждой перерисовке виджета, и контроллер
позволяет заново дослать кадры (из кэша) и восстановить состояние.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from collections import deque

from PIL import Image as PILImage
from textual.containers import Container
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

from telega.media.animation import Animation
from telega.ui.widgets import image as image_mod

log = logging.getLogger(__name__)

_CHUNK = 4096


class AnimationController:
    """Общее состояние анимации для native-режима (kitty)."""

    def __init__(self, animation: Animation) -> None:
        self.animation = animation
        self.playing = False
        self.image_id: int | None = None
        self._encoded: dict[tuple[int, int], list[str]] = {}

    def encoded_frames(self, width: int, height: int) -> list[str]:
        """Кадры (кроме первого) в PNG/base64 под нужный размер, с кэшем."""
        key = (width, height)
        if key not in self._encoded:
            started = time.perf_counter()
            out = []
            for frame in self.animation.frames[1:]:
                buf = io.BytesIO()
                frame.resize(key, PILImage.Resampling.BILINEAR).save(buf, "PNG", compress_level=1)
                out.append(base64.b64encode(buf.getvalue()).decode("ascii"))
            self._encoded[key] = out
            log.debug(
                "kitty: %d кадров %dx%d закодировано за %.0f мс, %d КБ",
                len(out), width, height, (time.perf_counter() - started) * 1000,
                sum(len(x) for x in out) // 1024,
            )
        return self._encoded[key]

    def apply_state(self) -> None:
        if self.image_id is None or not self.animation.animated:
            return
        from textual_image.renderable.tgp import _send_tgp_message

        if self.playing:
            # s=3 — проигрывать в цикле, v=1 — бесконечно
            _send_tgp_message(a="a", i=self.image_id, s=3, v=1, q=2)
        else:
            # s=1 — остановить, c=1 — показать первый кадр
            _send_tgp_message(a="a", i=self.image_id, s=1, c=1, q=2)


def _make_native_widget_class():
    """Класс виджета для kitty; создаётся лениво, т.к. импорт textual_image
    запускает опрос терминала (см. image.init_images)."""
    from textual_image.renderable.tgp import Image as TGPRenderable
    from textual_image.renderable.tgp import _send_tgp_message
    from textual_image.widget._base import Image as BaseImage

    class _AnimatedTGPRenderable(TGPRenderable):
        def __init__(self, image, width=None, height=None) -> None:
            super().__init__(image, width, height)
            info = getattr(image, "info", None) or {}
            self._ctrl: AnimationController | None = info.get("telega_anim")

        def _send_image_to_terminal(self, width: int, height: int) -> None:
            super()._send_image_to_terminal(width, height)
            ctrl = self._ctrl
            if ctrl is None or not ctrl.animation.animated:
                return
            image_id = self.terminal_image_id
            ctrl.image_id = image_id
            durations = ctrl.animation.durations
            for n, data in enumerate(ctrl.encoded_frames(width, height), start=1):
                first = True
                while data:
                    chunk, data = data[:_CHUNK], data[_CHUNK:]
                    if first:
                        _send_tgp_message(
                            a="f", i=image_id, f=100, z=durations[n], m=1 if data else 0,
                            q=2, payload=chunk,
                        )
                        first = False
                    else:
                        # продолжение передачи: по спецификации только m (и q)
                        _send_tgp_message(m=1 if data else 0, q=2, payload=chunk)
            # задержка для первого (базового) кадра
            _send_tgp_message(a="a", i=image_id, r=1, z=durations[0], q=2)
            ctrl.apply_state()

    class NativeAnimatedImage(BaseImage, Renderable=_AnimatedTGPRenderable):
        pass

    return NativeAnimatedImage


_native_cls = None


def native_supported(prefer_native: bool) -> bool:
    return prefer_native and image_mod.images_enabled() and image_mod.protocol_name() == "tgp"


class AnimatedImage(Container):
    """Анимация с методами play() / stop() и статистикой FPS."""

    # Контейнер занимает ширину родителя: при width:auto у контейнера и у
    # картинки внутри ширина вычисляется в 0 (каждый ждёт ширину от другого).
    DEFAULT_CSS = """
    AnimatedImage { width: 1fr; height: auto; }
    AnimatedImage > .anim-frame { width: auto; }
    """

    def __init__(
        self,
        animation: Animation,
        *,
        height: int,
        prefer_native: bool = True,
        classes: str = "",
    ) -> None:
        super().__init__(classes=classes)
        self.animation = animation
        self._height = height
        self.mode = "native" if native_supported(prefer_native) else "swap"
        self._ctrl = AnimationController(animation)
        self._timer: Timer | None = None
        self._index = 0
        self._inner: Widget | None = None
        self._shown: deque[float] = deque(maxlen=60)  # моменты смены кадров (swap)

    # --- построение ---

    def compose(self):
        first = self.animation.frames[0]
        if not image_mod.images_enabled():
            yield Static("[анимация: картинки отключены]", classes="image-fallback")
            return
        if self.mode == "native":
            global _native_cls
            if _native_cls is None:
                _native_cls = _make_native_widget_class()
            frame = first.copy()
            frame.info["telega_anim"] = self._ctrl
            self._inner = _native_cls(frame, classes="anim-frame")
        else:
            self._inner = image_mod.make_image(first, classes="anim-frame")
        self._inner.styles.height = self._height
        yield self._inner

    # --- управление ---

    @property
    def playing(self) -> bool:
        return self._ctrl.playing

    def play(self) -> None:
        if not self.animation.animated or self._ctrl.playing:
            return
        self._ctrl.playing = True
        if self.mode == "native":
            self._ctrl.apply_state()
        else:
            self._shown.clear()
            self._schedule()

    def stop(self) -> None:
        if not self._ctrl.playing:
            return
        self._ctrl.playing = False
        if self.mode == "native":
            self._ctrl.apply_state()
        else:
            if self._timer is not None:
                self._timer.stop()
                self._timer = None
            self._index = 0
            self._show(0)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    # --- swap-режим ---

    def _schedule(self) -> None:
        delay = self.animation.durations[self._index] / 1000
        self._timer = self.set_timer(delay, self._advance)

    def _advance(self) -> None:
        if not self._ctrl.playing:
            return
        self._index = (self._index + 1) % len(self.animation.frames)
        self._show(self._index)
        self._schedule()

    def _show(self, index: int) -> None:
        if self._inner is None or not hasattr(self._inner, "image"):
            return
        self._inner.image = self.animation.frames[index]
        self._shown.append(time.monotonic())

    # --- статистика ---

    @property
    def target_fps(self) -> float:
        d = self.animation.durations
        return 1000 * len(d) / max(1, sum(d))

    @property
    def actual_fps(self) -> float | None:
        """Реальная частота смены кадров (swap-режим) за последние ~60 кадров."""
        if self.mode == "native" or len(self._shown) < 5:
            return None
        span = self._shown[-1] - self._shown[0]
        return (len(self._shown) - 1) / span if span > 0 else None

    def describe(self) -> str:
        a = self.animation
        base = f"{len(a.frames)} кадров, {a.total_ms / 1000:.1f} с, цель {self.target_fps:.0f} fps"
        if self.mode == "native":
            return f"{base} · kitty-анимация"
        fps = self.actual_fps
        proto = image_mod.protocol_name()
        return f"{base} · смена кадров ({proto}): {f'{fps:.1f} fps' if fps else '…'}"
