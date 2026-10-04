"""Сквозные тесты интерфейса на DemoBackend через Textual Pilot."""

from __future__ import annotations

import pytest

from telega.backend.demo import ANNA, BOT, CHANNEL_ID, GROUP_ID, DemoBackend
from telega.config import Config
from telega.models import EntityKind
from telega.ui.app import TelegaApp
from telega.ui.screens.main import MainScreen
from telega.ui.screens.modals import ConfirmScreen, HelpScreen, ProfileScreen, ThemePickerScreen
from telega.ui.widgets.image import init_images
from telega.vim import Mode


@pytest.fixture
def app(tmp_path):
    init_images("unicode")  # в тестах нет настоящего терминала
    backend = DemoBackend(tmp_path / "media", echo_delay=0.05)
    return TelegaApp(Config(), backend)


async def _main(pilot) -> MainScreen:
    for _ in range(50):
        await pilot.pause(0.02)
        if isinstance(pilot.app.screen, MainScreen) and pilot.app.screen.chat_list.chats:
            return pilot.app.screen
    raise AssertionError("главный экран не загрузился")


async def _open(pilot, screen: MainScreen, chat_id: int) -> None:
    await screen.run_command(f"open {screen.chat_list.get(chat_id).title}")
    await pilot.pause(0.05)


async def test_navigation_and_open_chat(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        assert screen.mode is Mode.NORMAL
        await pilot.press("j", "j")
        assert screen.chat_list.highlighted == 2
        await pilot.press("g", "g")
        assert screen.chat_list.highlighted == 0
        await pilot.press("G")
        assert screen.chat_list.highlighted == len(screen.chat_list.chats) - 1
        await pilot.press("g", "g", "enter")
        await pilot.pause(0.05)
        assert screen.current_chat is not None
        assert screen.pane == "messages"
        assert screen.view.items


async def test_history_count_and_older(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        app.config.ui.history_limit = 10
        await _open(pilot, screen, GROUP_ID)
        assert len(screen.view.items) == 10
        last = screen.view.cursor
        await pilot.press("3", "k")
        assert screen.view.cursor == last - 3
        await pilot.press("g", "g", "k")  # у верхнего края — подгрузка истории
        await pilot.pause(0.05)
        assert len(screen.view.items) == 20


async def test_send_with_mention_completion(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        await _open(pilot, screen, GROUP_ID)
        await pilot.press("i")
        assert screen.mode is Mode.INSERT
        await pilot.press("@", "А", "н")
        await pilot.pause(0.3)  # debounce + поиск
        popup = screen.composer.popup
        assert popup.visible
        assert popup.selected_user.id == ANNA.id
        await pilot.press("enter")  # выбрать
        assert screen.composer.text == "Анна "
        await pilot.press(*"привет")
        await pilot.press("enter")  # отправить
        await pilot.pause(0.05)
        sent = screen.view.items[-1].message
        assert sent.text == "Анна привет"
        assert sent.entities[0].kind == EntityKind.MENTION_NAME
        assert sent.entities[0].user_id == ANNA.id
        await pilot.press("escape")
        assert screen.mode is Mode.NORMAL


async def test_incoming_event_from_bot(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        await _open(pilot, screen, BOT.id)
        await pilot.press("i", *"ping", "enter")
        await pilot.pause(0.3)
        texts = [i.message.text for i in screen.view.items]
        assert texts[-2:] == ["ping", "Эхо: ping"]


async def test_reply_edit_delete(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        await _open(pilot, screen, BOT.id)
        await pilot.press("i", *"one", "enter", "escape")
        await pilot.pause(0.2)
        # курсор на эхе бота → на своём сообщении
        screen.view.set_cursor(len(screen.view.items) - 2)
        await pilot.press("e")
        assert screen.mode is Mode.INSERT and screen.editing is not None
        await pilot.press("backspace", "backspace", "backspace", *"two", "enter")
        await pilot.pause(0.05)
        assert screen.view.items[-2].message.text == "two"
        assert screen.view.items[-2].message.edited
        await pilot.press("escape")
        await pilot.press("d", "d")
        await pilot.pause(0.05)
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await pilot.pause(0.05)
        assert "two" not in [i.message.text for i in screen.view.items]


async def test_images_load_in_channel(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        await _open(pilot, screen, CHANNEL_ID)
        await pilot.pause(0.3)
        with_images = [i for i in screen.view.items if i.message.has_image]
        assert with_images and all(i.image_path is not None for i in with_images)


async def test_profile_and_help(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        await pilot.press("K")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ProfileScreen)
        assert app.screen.query(".avatar")
        await pilot.press("q")
        await pilot.press("question_mark")
        await pilot.pause(0.05)
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        assert app.screen is screen


async def test_chat_filter_and_command(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        await pilot.press("slash", *"фото", "enter")
        assert screen.mode is Mode.NORMAL
        assert [c.id for c in screen.chat_list._visible] == [CHANNEL_ID]
        await pilot.press("escape")
        assert len(screen.chat_list._visible) == len(screen.chat_list.chats)
        await pilot.press("colon", *"open echo", "enter")
        await pilot.pause(0.05)
        assert screen.current_chat.id == BOT.id


async def test_hide_chat_list(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        chats = screen.chat_list
        await pilot.press("ctrl+n")  # чат не открыт — скрывать нельзя
        assert chats.display and not screen.chat_list_hidden

        await _open(pilot, screen, BOT.id)
        await pilot.press("ctrl+n")
        assert screen.chat_list_hidden and not chats.display
        assert screen.pane == "messages"
        assert screen.view.size.width > 100  # лента заняла место панели

        await pilot.press("h")  # выдвинуть временно
        assert chats.display and screen.pane == "chats"
        await pilot.press("g", "g", "enter")  # открыть чат — панель снова прячется
        await pilot.pause(0.05)
        assert not chats.display and screen.pane == "messages"

        await pilot.press("colon", *"sidebar on", "enter")
        assert chats.display and not screen.chat_list_hidden
        await pilot.press("colon", *"sidebar off", "enter")
        assert not chats.display


async def test_command_line_shows_typed_text(app):
    # Регрессия: рамка Input:focus съедала единственную строку, текст был не виден.
    async with app.run_test(size=(80, 20)) as pilot:
        screen = await _main(pilot)
        await pilot.press("colon", *"open")
        cmdline = screen.cmdline
        assert cmdline.value == "open"
        assert cmdline.content_region.height == 1
        assert "open" in app.export_screenshot()


async def test_leader_which_key(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        which = screen.which_key
        await pilot.press("space")
        assert which.visible and which.prefix == ("space",)
        assert dict(which.entries)["e"] == "toggle_chat_list"
        await pilot.press("escape")
        assert not which.visible and screen.parser.prefix == ()

        await _open(pilot, screen, BOT.id)
        await pilot.press("space", "e")  # <Space>e — скрыть список чатов
        assert not which.visible
        assert screen.chat_list_hidden and not screen.chat_list.display
        await pilot.press("space", "e")
        assert not screen.chat_list_hidden and screen.chat_list.display

        await pilot.press("space", "q")  # группа: окно показывает её содержимое
        assert which.visible and which.entries == [("q", "quit")]
        await pilot.press("backspace")  # назад к корню лидера
        assert which.prefix == ("space",)
        await pilot.press("space")  # <Space><Space> — найти чат
        assert screen.mode is Mode.SEARCH and screen.pane == "chats"
        assert not which.visible


async def test_which_key_delayed_for_g(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        await pilot.press("g")
        assert not screen.which_key.visible  # не мешает быстрому gg
        await pilot.pause(0.7)
        assert screen.which_key.visible
        await pilot.press("g")
        assert not screen.which_key.visible


async def test_theme_picker(tmp_path):
    init_images("unicode")
    config = Config(path=tmp_path / "config.toml")
    app = TelegaApp(config, DemoBackend(tmp_path / "media"))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        assert app.theme == "telega-cold"
        await pilot.press("space", "t")
        assert isinstance(app.screen, ThemePickerScreen)
        await pilot.press("j")  # предпросмотр без сохранения
        assert app.theme == "telega-warm" and config.ui.theme == "cold"
        await pilot.press("escape")  # отмена возвращает прежнюю
        assert app.theme == "telega-cold" and app.screen is screen

        await pilot.press("space", "t", "G", "enter")
        assert app.theme == "telega-bright" and not app.current_theme.dark
        assert config.ui.theme == "bright"
        assert 'theme = "bright"' in config.path.read_text()

        await screen.run_command("theme pastel")
        assert app.theme == "telega-pastel" and config.ui.theme == "pastel"
        await screen.run_command("theme neon")
        assert app.theme == "telega-pastel"


async def test_chat_list_hidden_from_config(tmp_path):
    init_images("unicode")
    config = Config()
    config.ui.show_chat_list = False
    app = TelegaApp(config, DemoBackend(tmp_path / "media"))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        assert screen.chat_list.display  # чат не открыт — панель видна, чтобы его выбрать
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert not screen.chat_list.display
