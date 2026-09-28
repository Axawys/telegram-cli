"""Декодирование анимаций в список кадров Pillow.

Форматы, которые встречаются в Telegram:
  .mp4        — «GIF» (Telegram перекодирует GIF в H.264 без звука)
  .webm       — видео-стикеры (VP9, часто с прозрачностью)
  .tgs        — анимированные стикеры (Lottie JSON, сжатый gzip)
  .webp/.gif  — статичные стикеры / настоящие GIF

Кадры сразу уменьшаются до `max_px` по большей стороне и прореживаются до
`max_fps`: в терминале больше не нужно, а память и время кодирования
(особенно sixel) растут пропорционально.

Декодирование — CPU-bound, вызывать через `asyncio.to_thread(load_animation, …)`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageSequence

log = logging.getLogger(__name__)

DEFAULT_MAX_PX = 320
DEFAULT_MAX_FPS = 20
DEFAULT_MAX_FRAMES = 150
_MIN_FRAME_MS = 20


@dataclass(slots=True)
class Animation:
    frames: list[Image.Image]  # RGBA
    durations: list[int]  # мс на каждый кадр

    @property
    def animated(self) -> bool:
        return len(self.frames) > 1

    @property
    def total_ms(self) -> int:
        return sum(self.durations)

    @property
    def size(self) -> tuple[int, int]:
        return self.frames[0].size


class AnimationError(Exception):
    pass


def _fit(img: Image.Image, max_px: int) -> Image.Image:
    img = img.convert("RGBA")
    if max(img.size) > max_px:
        img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    return img


def _thin(frames: list[tuple[Image.Image, float]], max_fps: int, max_frames: int) -> Animation:
    """(кадр, момент в секундах) → Animation с кадрами не чаще max_fps."""
    if not frames:
        raise AnimationError("нет кадров")
    step = 1.0 / max_fps
    kept: list[tuple[Image.Image, float]] = []
    next_t = -1.0
    for img, t in frames:
        if t + 1e-6 >= next_t:
            kept.append((img, t))
            next_t = t + step
        if len(kept) >= max_frames:
            break
    durations = []
    for i, (_, t) in enumerate(kept):
        nxt = kept[i + 1][1] if i + 1 < len(kept) else t + step
        durations.append(max(_MIN_FRAME_MS, round((nxt - t) * 1000)))
    return Animation([img for img, _ in kept], durations)


def _load_tgs(path: Path, max_px: int, max_fps: int, max_frames: int) -> Animation:
    from rlottie_python import LottieAnimation

    anim = LottieAnimation.from_tgs(str(path))
    total = anim.lottie_animation_get_totalframe()
    fps = anim.lottie_animation_get_framerate() or 30
    w, h = anim.lottie_animation_get_size()
    scale = min(1.0, max_px / max(w, h))
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    # Lottie рендерится по номеру кадра — сразу берём каждый k-й.
    out_fps = min(fps, max_fps)
    count = max(1, min(max_frames, round(total * out_fps / fps)))
    frames = []
    for i in range(count):
        n = min(total - 1, round(i * fps / out_fps))
        img = anim.render_pillow_frame(frame_num=n, width=size[0], height=size[1])
        frames.append(img.convert("RGBA"))
    duration = max(_MIN_FRAME_MS, round(1000 / out_fps))
    return Animation(frames, [duration] * len(frames))


def _frame_to_rgba(frame) -> Image.Image:
    """Кадр PyAV → RGBA. `frame.to_image()` отбрасывает альфа-канал, поэтому
    собираем картинку из буфера сами (строки могут быть выровнены — line_size)."""
    rgba = frame.reformat(format="rgba")
    plane = rgba.planes[0]
    return Image.frombuffer(
        "RGBA", (rgba.width, rgba.height), bytes(plane), "raw", "RGBA", plane.line_size, 1
    )


def _load_video(path: Path, max_px: int, max_fps: int, max_frames: int) -> Animation:
    import av

    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        codec = stream.codec_context.name
        # Нативный декодер ffmpeg для VP9 теряет альфа-канал, libvpx — нет.
        decoder = None
        if codec == "vp9":
            decoder = av.CodecContext.create("libvpx-vp9", "r")
        elif codec == "vp8":
            decoder = av.CodecContext.create("libvpx", "r")
        if decoder is not None and stream.codec_context.extradata:
            decoder.extradata = stream.codec_context.extradata

        time_base = float(stream.time_base) if stream.time_base else 1 / 30
        frames: list[tuple[Image.Image, float]] = []
        next_t = -1.0
        step = 1.0 / max_fps

        def take(frame) -> bool:
            nonlocal next_t
            t = float(frame.pts * time_base) if frame.pts is not None else len(frames) * step
            if t + 1e-6 >= next_t:
                frames.append((_fit(_frame_to_rgba(frame), max_px), t))
                next_t = t + step
            return len(frames) < max_frames

        if decoder is None:
            for frame in container.decode(stream):
                if not take(frame):
                    break
        else:
            done = False
            for packet in container.demux(stream):
                for frame in decoder.decode(packet):
                    if not take(frame):
                        done = True
                        break
                if done:
                    break
    return _thin(frames, max_fps, max_frames)


def _load_pillow(path: Path, max_px: int, max_fps: int, max_frames: int) -> Animation:
    with Image.open(path) as img:
        frames: list[tuple[Image.Image, float]] = []
        t = 0.0
        for frame in ImageSequence.Iterator(img):
            frames.append((_fit(frame.copy(), max_px), t))
            t += (frame.info.get("duration") or 100) / 1000
            if len(frames) >= max_frames * 4:
                break
    return _thin(frames, max_fps, max_frames)


def load_animation(
    path: Path,
    *,
    max_px: int = DEFAULT_MAX_PX,
    max_fps: int = DEFAULT_MAX_FPS,
    max_frames: int = DEFAULT_MAX_FRAMES,
) -> Animation:
    """Загрузить файл как последовательность кадров (статичная картинка → 1 кадр)."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".tgs":
            return _load_tgs(path, max_px, max_fps, max_frames)
        if suffix in (".mp4", ".webm", ".mov", ".mkv"):
            return _load_video(path, max_px, max_fps, max_frames)
        return _load_pillow(path, max_px, max_fps, max_frames)
    except AnimationError:
        raise
    except Exception as exc:
        log.exception("load_animation %s", path)
        raise AnimationError(f"{type(exc).__name__}: {exc}") from exc
