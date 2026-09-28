"""Анимации: декодирование форматов Telegram и воспроизведение в UI."""

from __future__ import annotations

import pytest

from telega.backend import demo_media
from telega.backend.demo import ANIM_ID, DemoBackend
from telega.config import Config
from telega.media.animation import load_animation
from telega.ui.app import TelegaApp
from telega.ui.screens.main import MainScreen
from telega.ui.screens.modals import ImageViewerScreen
from telega.ui.widgets.image import init_images


@pytest.mark.parametrize(
    ("maker", "name", "animated", "transparent"),
    [
        (demo_media.make_gif_mp4, "g.mp4", True, False),
        (demo_media.make_webm_sticker, "s.webm", True, True),
        (demo_media.make_tgs_sticker, "s.tgs", True, True),
        (demo_media.make_webp_sticker, "s.webp", False, True),
    ],
)
def test_decode_formats(tmp_path, maker, name, animated, transparent):
    anim = load_animation(maker(tmp_path / name), max_px=128)
    assert anim.animated is animated
    assert len(anim.frames) == len(anim.durations)
    assert max(anim.size) <= 128
    assert all(f.mode == "RGBA" for f in anim.frames)
    min_alpha = min(f.getextrema()[3][0] for f in anim.frames)
    assert (min_alpha == 0) is transparent  # прозрачность webm/tgs/webp не теряется


def test_decode_respects_fps_and_frame_limits(tmp_path):
    path = demo_media.make_gif_mp4(tmp_path / "g.mp4", frames=40, fps=20)
    assert len(load_animation(path).frames) == 40
    assert len(load_animation(path, max_fps=10).frames) == 20
    assert len(load_animation(path, max_frames=5).frames) == 5
    assert len(load_animation(path, max_frames=1).frames) == 1


async def _main(pilot) -> MainScreen:
    for _ in range(50):
        await pilot.pause(0.02)
        if isinstance(pilot.app.screen, MainScreen) and pilot.app.screen.chat_list.chats:
            return pilot.app.screen
    raise AssertionError("главный экран не загрузился")


async def test_selected_animation_plays(tmp_path):
    init_images("unicode")
    app = TelegaApp(Config(path=tmp_path / "c.toml"), DemoBackend(tmp_path / "media"))
    async with app.run_test(size=(120, 50)) as pilot:
        screen = await _main(pilot)
        await screen.run_command("open Стикеры")
        for _ in range(100):
            await pilot.pause(0.05)
            animated = [i for i in screen.view.items if i.animated is not None]
            if len(animated) == 4:
                break
        assert len(animated) == 4, "все GIF/стикеры должны загрузиться"

        # курсор на последнем (статичный webp) — ничего не играет
        assert not any(i.animated.playing for i in animated)
        await pilot.press("k")  # webm-стикер
        webm = screen.view.items[screen.view.cursor].animated
        assert webm.playing and webm.mode == "swap"
        await pilot.pause(0.5)
        assert webm.actual_fps and webm.actual_fps > 5
        await pilot.press("k")
        assert not webm.playing, "анимация останавливается, когда курсор уходит"

        await pilot.press("o")  # tgs на весь экран
        for _ in range(40):
            await pilot.pause(0.05)
            if isinstance(app.screen, ImageViewerScreen):
                break
        viewer = app.screen
        assert isinstance(viewer, ImageViewerScreen) and viewer.animated.playing
        await pilot.press("q")
        await pilot.pause(0.05)
        assert screen.view.items[screen.view.cursor].animated.playing  # лента снова играет


async def test_animations_off_shows_first_frame(tmp_path):
    init_images("unicode")
    config = Config(path=tmp_path / "c.toml")
    config.ui.animations = "off"
    app = TelegaApp(config, DemoBackend(tmp_path / "media"))
    async with app.run_test(size=(120, 50)) as pilot:
        screen = await _main(pilot)
        await screen.run_command("open Стикеры")
        for _ in range(100):
            await pilot.pause(0.05)
            animated = [i for i in screen.view.items if i.animated is not None]
            if len(animated) == 4:
                break
        assert all(len(i.animated.animation.frames) == 1 for i in animated)
        assert not any(i.animated.playing for i in animated)
        assert ANIM_ID == screen.current_chat.id
