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


async def test_chat_avatars_lazy_and_rows_kept(app):
    async with app.run_test(size=(120, 10)) as pilot:  # видно ~4 чата из 6
        screen = await _main(pilot)
        chats = screen.chat_list
        await pilot.pause(0.5)
        rows = chats._rows
        order = [c.id for c in chats.visible]
        loaded = {cid for cid, row in rows.items() if row.avatar_path is not None}
        assert loaded and order[-1] not in loaded  # нижние ещё не видны — не качаем
        assert rows[BOT.id].avatar_path is None  # у бота нет фото — инициалы
        assert "EB" in str(rows[BOT.id].query_one(".avatar-initials").render())

        await pilot.press("G")  # прокрутка вниз догружает остальные
        await pilot.pause(0.5)
        assert rows[order[-1]].avatar_path is not None

        # Новое сообщение поднимает чат вверх, но строку не пересоздаёт.
        bot_row = rows[BOT.id]
        await _open(pilot, screen, BOT.id)
        await pilot.press("i", *"ping", "enter")
        await pilot.pause(0.3)
        assert chats._rows[BOT.id] is bot_row
        assert list(chats.children).index(bot_row) == [c.id for c in chats.visible].index(BOT.id)
        assert "ping" in str(bot_row.query_one(".chat-preview").render())

        chats.set_filter("echo")
        await pilot.pause(0.05)
        assert [c.id for c in chats.visible] == [BOT.id]
        assert sum(1 for r in rows.values() if r.display) == 1


async def test_sender_avatars_in_group(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        await _open(pilot, screen, GROUP_ID)
        await pilot.pause(0.5)
        items = screen.view.items
        assert all(i.avatar is not None for i in items)
        for prev, item in zip(items, items[1:], strict=False):
            continued = item.message.sender_id == prev.message.sender_id
            assert item.avatar.has_class("-continued") == continued
        first = items[-1]
        assert first.avatar.path is not None  # скачана и показана

        await pilot.press("i", *"всем привет", "enter")  # своё сообщение тоже с аватаркой
        await pilot.pause(0.3)
        mine = screen.view.items[-1]
        assert mine.message.outgoing and mine.avatar is not None

        await _open(pilot, screen, BOT.id)  # в личке аватарок нет
        await pilot.pause(0.2)
        assert all(i.avatar is None for i in screen.view.items)


async def test_feed_follows_new_messages_when_last_selected(app):
    import asyncio
    from datetime import datetime, timezone

    from telega.backend import NewMessageEvent
    from telega.backend.demo import MARIA
    from telega.models import MediaKind, Message

    def incoming(msg_id: int, **kw) -> NewMessageEvent:
        return NewMessageEvent(Message(
            id=msg_id, chat_id=GROUP_ID, date=datetime.now(timezone.utc), text="новое",
            sender_id=MARIA.id, sender_name="Мария", **kw,
        ))

    async with app.run_test(size=(110, 30)) as pilot:
        screen = await _main(pilot)
        await _open(pilot, screen, GROUP_ID)
        await pilot.pause(0.5)
        view = screen.view
        assert view.following
        assert view.items[-1].has_class("-selected")
        assert view.items[-1].styles.background.a > 0  # подсвечено целиком, не только полоска

        # Картинка приходит из сети позже, чем сообщение: лента должна остаться внизу.
        download = screen.backend.download_image

        async def slow(message):
            await asyncio.sleep(0.4)
            return await download(message)

        screen.backend.download_image = slow
        await screen.handle_backend_event(incoming(9100, media=MediaKind.PHOTO, media_label="фото"))
        await pilot.pause(0.9)
        assert view.items[-1].image_path is not None
        assert view.cursor == len(view.items) - 1
        assert view.scroll_y == view.max_scroll_y

        # Выделено не последнее — новое сообщение не сдвигает ни курсор, ни ленту.
        await pilot.press("k")
        cursor, scroll = view.cursor, view.scroll_y
        await screen.handle_backend_event(incoming(9101))
        await pilot.pause(0.2)
        assert view.cursor == cursor and view.scroll_y == scroll
        assert view.scroll_y < view.max_scroll_y


async def test_leader_reply_and_goto_original(tmp_path):
    init_images("unicode")
    config = Config(path=tmp_path / "config.toml")
    config.ui.history_limit = 10  # исходное сообщение окажется за пределами первой страницы
    app = TelegaApp(config, DemoBackend(tmp_path / "media", echo_delay=0.05))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        await _open(pilot, screen, GROUP_ID)
        view = screen.view
        reply = view.selected
        assert reply.text.startswith("Возвращаясь") and reply.reply_to_id is not None
        assert view.index_of(reply.reply_to_id) is None  # ещё не загружено

        await pilot.press("space", "o")  # к исходному: подгружает историю
        await pilot.pause(0.2)
        assert view.selected.id == reply.reply_to_id
        assert view.selected.text == "Сообщение истории №3"
        assert screen.pane == "messages"

        # Вглубь по цепочке: №3 сам ответ на №1.
        await pilot.press("space", "o")
        await pilot.pause(0.2)
        assert view.selected.text == "Сообщение истории №1"
        third = reply.reply_to_id

        await pilot.press("ctrl+o")  # назад — к №3
        assert view.selected.id == third
        await pilot.press("space", "b")  # и ещё назад — к исходной точке
        assert view.selected.id == reply.id
        await pilot.press("ctrl+o")  # дальше некуда
        assert view.selected.id == reply.id and "переходов нет" in screen.status.note

        await pilot.press("2", "space", "f")  # вперёд сразу на два шага
        assert view.selected.text == "Сообщение истории №1"
        await pilot.press("2", "ctrl+o")  # и назад на два
        assert view.selected.id == reply.id

        await pilot.press("space", "o")  # новый переход обрывает «вперёд»
        assert screen._jump_forward == []

        await pilot.press("G")
        await pilot.press("space", "r")  # ответить на выделенное
        assert screen.mode is Mode.INSERT and screen.reply_to.id == reply.id
        await pilot.press("escape")

        await pilot.press("space", "R", "c")  # обновление переехало на Space R
        await pilot.pause(0.2)
        await pilot.press("G", "k")  # предпоследнее — не ответ: подсказка, без падения
        await pilot.press("space", "o")
        assert "не ответ" in screen.status.note


async def test_reactions_shown_and_toggled(app):
    from telega.ui.screens.modals import ReactionPickerScreen

    def line(item) -> str:
        return str(item.reactions_widget.render())

    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        await _open(pilot, screen, GROUP_ID)
        view = screen.view
        index = next(i for i, it in enumerate(view.items) if "#roadmap" in it.message.text)
        item = view.items[index]
        # Telegram присылает лишь последних поставивших — «и ещё N».
        assert "👍 4 ✓: @durov, @masha и ещё 2" in line(item)
        assert "🤡 1: Анна Смирнова" in line(item)

        view.set_cursor(index)  # выделили — догружается полный список
        await pilot.pause(0.7)
        assert "👍 4 ✓: @durov, @masha, Анна Смирнова, вы" in line(item)

        await pilot.press("space", "l")  # группа «реакция» в меню подсказок
        entries = dict(screen.which_key.entries)
        assert entries["c"] == "react:🤡" and entries["/"] == "react" and entries["x"] == "unreact"
        await pilot.press("slash")  # «/» — все реакции с поиском
        assert isinstance(app.screen, ReactionPickerScreen)
        await pilot.press(*"clo", "enter")  # поиск по названию → clown
        await pilot.pause(0.7)
        assert app.screen is screen
        reactions = {r.emoji: r for r in item.message.reactions}
        assert reactions["🤡"].chosen and reactions["🤡"].count == 2
        assert reactions["👍"].count == 3 and not reactions["👍"].chosen  # заменила прежнюю
        assert "🤡 2 ✓" in line(item)

        await screen.run_command("react clown")  # повторно — снимает
        assert not any(r.chosen for r in item.message.reactions)

        await pilot.press("space", "l", "h")  # прямо из меню: Space l h — heart
        await pilot.pause(0.1)
        assert {r.emoji for r in item.message.reactions if r.chosen} == {"❤"}
        await pilot.press("space", "l", "x")  # снять свою
        await pilot.pause(0.1)
        assert not any(r.chosen for r in item.message.reactions)

        await pilot.press("space", "l", "slash", "escape")  # отмена ничего не меняет
        assert not any(r.chosen for r in item.message.reactions)

        await _open(pilot, screen, CHANNEL_ID)  # в канале — только счётчики
        post = screen.view.items[0]
        assert line(post).startswith("🔥 154   ❤\ufe0f 37")
        await screen.run_command("react clown")  # канал ограничил набор
        assert "Нет такой реакции" in screen.status.note
        await pilot.press("space", "l", "c")
        assert "запрещена" in screen.status.note


async def test_paste_image_and_send(tmp_path, monkeypatch):
    from PIL import Image as PILImage

    from telega import clipboard

    init_images("unicode")
    picture = tmp_path / "shot.png"
    PILImage.new("RGB", (320, 200), (40, 120, 200)).save(picture)
    clip = {"value": clipboard.ClipboardContent(image=picture)}

    async def fake_read(dest_dir):
        return clip["value"]

    monkeypatch.setattr(clipboard, "read_clipboard", fake_read)
    app = TelegaApp(Config(path=tmp_path / "c.toml"), DemoBackend(tmp_path / "media", echo_delay=5))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _main(pilot)
        await _open(pilot, screen, GROUP_ID)

        await pilot.press("i", "ctrl+v")  # картинка из буфера → вложение
        await pilot.pause(0.2)
        assert screen.attachment == picture
        box = screen.query_one("#attachment")
        assert box.display and "320×200" in str(screen.query_one("#attachment-label").render())
        assert screen.query("#attachment-preview")  # превью

        await pilot.press("escape")  # Esc убирает вложение
        assert screen.attachment is None and not box.has_class("-visible")

        await pilot.press("ctrl+v")  # из NORMAL: сразу в поле ввода с картинкой
        await pilot.pause(0.2)
        assert screen.mode is Mode.INSERT and screen.attachment == picture
        await pilot.press(*"скрин", "enter")  # текст — подпись
        await pilot.pause(0.3)
        sent = screen.view.items[-1]
        assert sent.message.has_image and sent.message.text == "скрин" and sent.message.outgoing
        assert sent.image_path == picture  # своя картинка не качается обратно
        assert screen.attachment is None and screen.composer.text == ""

        await pilot.press("ctrl+v", "enter")  # без подписи тоже можно
        await pilot.pause(0.3)
        assert screen.view.items[-1].message.has_image and screen.view.items[-1].message.text == ""

        clip["value"] = clipboard.ClipboardContent(text="просто текст")  # текст — вставкой
        await pilot.press("ctrl+v")
        await pilot.pause(0.2)
        assert screen.composer.text == "просто текст" and screen.attachment is None


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
        assert screen.pane == "chats"  # открыли список — фокус на нём
        assert screen.chat_list.selected.id == BOT.id  # курсор на текущем чате

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


async def test_sixel_output_matches_cells(tmp_path):
    # Исправления sixel для foot (см. _fixed_sixel_class): курсор после
    # картинки, место частично перерисованного куска и лишняя полоса.
    from PIL import Image as PILImage
    from rich.control import Control
    from textual.app import App
    from textual.geometry import Region

    from telega.ui.widgets import image as image_mod

    path = tmp_path / "a.png"
    PILImage.new("RGB", (160, 100), (10, 20, 30)).save(path)
    init_images("sixel")
    try:
        widget = image_mod.make_image(path)
        widget.styles.width, widget.styles.height = 8, 4

        class Host(App):
            def compose(self):
                yield widget

        async with Host().run_test(size=(40, 10)) as pilot:
            await pilot.pause(0.05)
            impl = widget.children[0]
            region = impl.screen.find_widget(impl).region

            def moves(crop):
                impl._crop = crop
                segments = impl._get_sixel_segments("SIXEL")
                return segments[0].text, segments[-1].text

            # Вся картинка: курсор возвращается на её ПОСЛЕДНЮЮ строку, а не под неё.
            start, end = moves(Region(0, 0, 8, 4))
            assert start == Control.move_to(region.x, region.y).segment.text
            assert end == Control.move_to(region.x + 8, region.y + 3).segment.text
            # Кусок (строки 2–3): рисуется на своём месте, а не в верхнем углу.
            start, end = moves(Region(0, 2, 8, 2))
            assert start == Control.move_to(region.x, region.y + 2).segment.text
            assert end == Control.move_to(region.x + 8, region.y + 3).segment.text

            # 50 px = 8 полос + 2 строки: ровно 9 полос, без «-» после последней,
            # а добив до 54 — прозрачный (P2=1), не чёрный.
            data = impl._image_to_sixels(PILImage.new("RGB", (16, 50), (200, 0, 0)))
            assert data.endswith("\x1b\\") and not data.endswith("-\x1b\\")
            assert data[data.index('"'):].count("-") == 9 - 1
            assert data.startswith("\x1bP0;1;")  # P2=1: незаданные пиксели прозрачны
            # Кратная 6 высота — без изменений и без прозрачности.
            data = impl._image_to_sixels(PILImage.new("RGB", (16, 48), (200, 0, 0)))
            assert data.startswith("\x1bP0;0;") and data[data.index('"'):].count("-") == 8 - 1
    finally:
        init_images("unicode")
