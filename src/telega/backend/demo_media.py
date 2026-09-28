"""Генерация демо-медиа в тех же форматах, что присылает Telegram.

Используется DemoBackend и тестами: GIF (MP4/H.264), анимированный стикер
(.tgs — Lottie в gzip), видео-стикер (.webm VP9 с прозрачностью) и
статичный стикер (.webp).
"""

from __future__ import annotations

import gzip
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw


def _ball_frame(i: int, n: int, size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, (40, 44, 52))
    draw = ImageDraw.Draw(img)
    t = i / n
    x = w * 0.15 + (w * 0.7) * (0.5 - 0.5 * math.cos(2 * math.pi * t))
    y = h * 0.8 - abs(math.sin(2 * math.pi * t * 2)) * h * 0.55
    r = h * 0.1
    draw.ellipse([x - r, y - r, x + r, y + r], fill=(229, 192, 123))
    draw.rectangle([0, h * 0.9, w, h], fill=(97, 175, 239))
    return img


def make_gif_mp4(path: Path, frames: int = 40, fps: int = 20) -> Path:
    """«GIF» как в Telegram: H.264 без звука."""
    import av

    size = (320, 240)
    with av.open(str(path), "w") as out:
        stream = out.add_stream("libx264", rate=fps)
        stream.width, stream.height = size
        stream.pix_fmt = "yuv420p"
        for i in range(frames):
            frame = av.VideoFrame.from_image(_ball_frame(i, frames, size))
            out.mux(stream.encode(frame))
        out.mux(stream.encode())
    return path


def make_webm_sticker(path: Path, frames: int = 30, fps: int = 30) -> Path:
    """Видео-стикер: VP9 с альфа-каналом, 512×512 как в Telegram."""
    import av

    size = 256
    with av.open(str(path), "w", format="webm") as out:
        stream = out.add_stream("libvpx-vp9", rate=fps)
        stream.width = stream.height = size
        stream.pix_fmt = "yuva420p"
        stream.options = {"auto-alt-ref": "0"}  # иначе libvpx не пишет альфу
        for i in range(frames):
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            k = 0.6 + 0.3 * math.sin(2 * math.pi * i / frames)
            r = size / 2 * k
            c = size / 2
            draw.ellipse([c - r, c - r, c + r, c + r], fill=(224, 108, 117, 255))
            draw.ellipse([c - r * 0.5, c - r * 0.5, c + r * 0.5, c + r * 0.5], fill=(0, 0, 0, 0))
            # from_image() теряет альфу (переводит в RGB) — заполняем RGBA-кадр сами.
            frame = av.VideoFrame(size, size, "rgba")
            plane = frame.planes[0]
            row = size * 4
            data = img.tobytes()
            if plane.line_size == row:
                plane.update(data)
            else:
                padded = b"".join(
                    data[y * row:(y + 1) * row].ljust(plane.line_size, b"\0") for y in range(size)
                )
                plane.update(padded)
            frame = frame.reformat(format="yuva420p")
            out.mux(stream.encode(frame))
        out.mux(stream.encode())
    return path


def make_tgs_sticker(path: Path) -> Path:
    """Анимированный стикер: вращающийся и пульсирующий квадрат (Lottie 5.x)."""

    def anim(k0, k1, frames=60):
        return {
            "a": 1,
            "k": [
                {"t": 0, "s": k0, "e": k1, "i": {"x": [0.5], "y": [0.5]}, "o": {"x": [0.5], "y": [0.5]}},
                {"t": frames // 2, "s": k1, "e": k0, "i": {"x": [0.5], "y": [0.5]},
                 "o": {"x": [0.5], "y": [0.5]}},
                {"t": frames},
            ],
        }

    lottie = {
        "v": "5.5.2", "fr": 30, "ip": 0, "op": 60, "w": 512, "h": 512, "tgs": 1, "ddd": 0,
        "assets": [],
        "layers": [{
            "ddd": 0, "ind": 1, "ty": 4, "nm": "square", "sr": 1, "ip": 0, "op": 60, "st": 0,
            "ks": {
                "o": {"a": 0, "k": 100},
                "r": {"a": 1, "k": [
                    {"t": 0, "s": [0], "e": [360], "i": {"x": [0.5], "y": [0.5]}, "o": {"x": [0.5], "y": [0.5]}},
                    {"t": 60},
                ]},
                "p": {"a": 0, "k": [256, 256, 0]},
                "a": {"a": 0, "k": [0, 0, 0]},
                "s": anim([70, 70, 100], [110, 110, 100]),
            },
            "shapes": [{
                "ty": "gr", "nm": "g",
                "it": [
                    {"ty": "rc", "d": 1, "s": {"a": 0, "k": [240, 240]}, "p": {"a": 0, "k": [0, 0]},
                     "r": {"a": 0, "k": 48}},
                    {"ty": "fl", "c": {"a": 0, "k": [0.6, 0.76, 0.47, 1]}, "o": {"a": 0, "k": 100}},
                    {"ty": "tr", "p": {"a": 0, "k": [0, 0]}, "a": {"a": 0, "k": [0, 0]},
                     "s": {"a": 0, "k": [100, 100]}, "r": {"a": 0, "k": 0}, "o": {"a": 0, "k": 100}},
                ],
            }],
        }],
    }
    path.write_bytes(gzip.compress(json.dumps(lottie).encode()))
    return path


def make_webp_sticker(path: Path) -> Path:
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon(
        [(size / 2 + size * 0.45 * math.cos(a * math.pi / 5 - math.pi / 2) * (1 if a % 2 == 0 else 0.45),
          size / 2 + size * 0.45 * math.sin(a * math.pi / 5 - math.pi / 2) * (1 if a % 2 == 0 else 0.45))
         for a in range(10)],
        fill=(229, 192, 123, 255),
    )
    img.save(path, "WEBP")
    return path
