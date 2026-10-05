"""Главный экран: список чатов + лента + поле ввода.

Здесь живёт vim-диспетчер. В NORMAL-режиме фокуса нет ни у одного виджета,
все клавиши приходят в `on_key` экрана → `KeyParser` → метод `vim_<действие>`.
В INSERT-режиме фокус у Composer, в COMMAND/SEARCH — у CommandLine; Esc
возвращает в NORMAL.

Добавить vim-действие:
  1. строка в telega/vim/keymap.py («последовательность»: «имя»);
  2. метод `vim_<имя>(self, action: Action)` ниже;
  3. описание в ACTION_HELP (telega/vim/keymap.py) и docs/KEYBINDINGS.md.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image as PILImage
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from telega.backend import (
    Backend,
    BackendEvent,
    MessageEditedEvent,
    MessagesDeletedEvent,
    NewMessageEvent,
)
from telega import clipboard
from telega.config import THEMES, Config, ConfigError, save_theme
from telega.mentions import Mention
from telega.media.animation import DEFAULT_MAX_FRAMES, Animation, load_animation
from telega.models import BackendError, Chat, ChatKind, EntityKind, MediaKind, Message
from telega.text import shorten
from telega.reactions import filter_reactions, reaction_name
from telega.ui.render import KIND_NAMES
from telega.ui.themes import SPECS, apply_theme
from telega.ui.screens.modals import (
    ConfirmScreen,
    HelpScreen,
    ImageViewerScreen,
    ProfileScreen,
    ReactionPickerScreen,
    ThemePickerScreen,
)
from telega.ui.widgets.chat_list import ChatList
from telega.ui.widgets.composer import Composer, MentionPopup
from telega.ui.widgets.image import images_enabled, make_image, protocol_name
from telega.ui.widgets.message_view import MessageItem, MessageView
from telega.ui.widgets.status import CommandLine, StatusLine
from telega.ui.widgets.which_key import WhichKey
from telega.vim import DEFAULT_KEYMAP, Action, KeyParser, Mode, token_from_event

log = logging.getLogger(__name__)

CHATS, MESSAGES = "chats", "messages"
# Сколько картинок качать одновременно.
_IMAGE_CONCURRENCY = 3
# Пауза перед поиском участников, чтобы не дёргать сервер на каждую букву.
_MENTION_DEBOUNCE = 0.15
# Размер кадров анимации (px по большей стороне): в ленте и на весь экран.
_FEED_ANIM_PX = 256
_VIEWER_ANIM_PX = 640
# Через сколько секунд показывать подсказки после префикса (g, d …).
# После лидера (<Space>) окно появляется сразу.
_WHICH_KEY_DELAY = 0.5
_LEADER = "space"
# Сколько страниц истории подгружать в поисках исходного сообщения (gr, Space o).
_GOTO_REPLY_PAGES = 10
# Пауза перед догрузкой полного списка поставивших реакции: не дёргать сервер,
# пока курсор быстро бежит по ленте.
_REACTION_USERS_DELAY = 0.4


class MainScreen(Screen):
    AUTO_FOCUS = None

    DEFAULT_CSS = """
    MainScreen { layout: vertical; }
    #main { height: 1fr; }
    #chats { border-right: vkey $panel; }
    #chats.-active { border-right: vkey $accent; }
    #chat-pane { width: 1fr; }
    #chat-header {
        height: 1;
        padding: 0 1;
        background: $panel;
        text-style: bold;
    }
    #chat-pane.-active #chat-header { background: $accent 40%; }
    #compose-banner {
        display: none;
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #compose-banner.-visible { display: block; }
    #attachment { display: none; height: auto; padding: 0 1; }
    #attachment.-visible { display: block; }
    #attachment-preview { width: auto; height: 5; margin-right: 1; }
    #attachment-label { width: 1fr; height: auto; color: $text-muted; }
    #composer { display: none; }
    #composer.-visible { display: block; }
    #cmdbar { display: none; height: 1; }
    #cmdbar.-visible { display: block; }
    #cmd-prefix { width: 1; height: 1; }
    """

    def __init__(self, backend: Backend, config: Config) -> None:
        super().__init__()
        self.backend = backend
        self.config = config
        self.parser = KeyParser(DEFAULT_KEYMAP)
        self.mode = Mode.NORMAL
        self.pane = CHATS
        self.current_chat: Chat | None = None
        self.reply_to: Message | None = None
        self.editing: Message | None = None
        self.search_query = ""
        self._loading_history = False
        self._history_exhausted = False
        # Список переходов по ответам (как jumplist в vim): id сообщений, откуда
        # уходили (назад) и куда возвращались (вперёд). Свой у каждого чата —
        # сбрасывается при открытии другого.
        # Картинка, вставленная Ctrl+V и ждущая отправки.
        self.attachment: Path | None = None
        self._jump_back: list[int] = []
        self._jump_forward: list[int] = []
        # Пользователь скрыл левую панель (<C-n> / :sidebar).
        self.chat_list_hidden = not config.ui.show_chat_list
        self._image_sem = asyncio.Semaphore(_IMAGE_CONCURRENCY)
        self._which_key_timer = None
        self._avatar_sem = asyncio.Semaphore(_IMAGE_CONCURRENCY)
        # Маленькие аватарки по id: общие для списка чатов и ленты (у личного
        # чата и пользователя один id). None — фото нет или не скачалось.
        self._avatars: dict[int, Path | None] = {}
        self._avatar_tasks: dict[int, asyncio.Future[Path | None]] = {}
        # Для каких (чат, сообщение, счётчики) уже догружали поставивших реакции.
        self._reaction_users_loaded: set[tuple] = set()

    # --- построение ------------------------------------------------------

    def compose(self) -> ComposeResult:
        ui = self.config.ui
        popup = MentionPopup(id="mentions")
        with Horizontal(id="main"):
            yield ChatList(id="chats", show_avatars=ui.chat_avatars)
            with Vertical(id="chat-pane"):
                yield Static("Выберите чат", id="chat-header")
                yield MessageView(
                    id="messages",
                    time_format=ui.time_format,
                    date_format=ui.date_format,
                    image_height=ui.image_height,
                )
                yield Static(id="compose-banner")
                with Horizontal(id="attachment"):
                    yield Static(id="attachment-label")
                yield popup
                yield Composer(popup, id="composer")
        yield WhichKey(id="which-key")
        with Horizontal(id="cmdbar"):
            yield Static(":", id="cmd-prefix")
            yield CommandLine(id="cmdline")
        yield StatusLine(id="status")

    @property
    def chat_list(self) -> ChatList:
        return self.query_one(ChatList)

    @property
    def view(self) -> MessageView:
        return self.query_one(MessageView)

    @property
    def composer(self) -> Composer:
        return self.query_one(Composer)

    @property
    def cmdline(self) -> CommandLine:
        return self.query_one(CommandLine)

    @property
    def status(self) -> StatusLine:
        return self.query_one(StatusLine)

    @property
    def which_key(self) -> WhichKey:
        return self.query_one(WhichKey)

    def on_mount(self) -> None:
        self.view.autoplay_selected = self.config.ui.animations == "selected"
        if self.backend.me:
            self.view.my_username = self.backend.me.username
        self._set_pane(CHATS)
        self._set_mode(Mode.NORMAL)
        images = protocol_name() if images_enabled() else "выкл"
        if self.config.warnings:
            self.notify_status(f"Конфиг: {'; '.join(self.config.warnings)}", error=True)
        else:
            self.notify_status(f"Картинки: {images}.  ? — справка, :q — выход")
        self.load_chats()

    # --- состояние -------------------------------------------------------

    def notify_status(self, text: str, *, error: bool = False) -> None:
        self.status.notify_text(text, error=error)
        if error:
            log.warning(text)

    def _set_mode(self, mode: Mode) -> None:
        self.mode = mode
        self.parser.reset()
        self._update_which_key()
        self.status.set_state(mode=mode, pending="")

    def _set_pane(self, pane: str) -> None:
        self.pane = pane
        # Скрытый список чатов работает как выдвижная панель: виден, пока на нём фокус.
        self.chat_list.display = not self.chat_list_hidden or pane == CHATS
        self.chat_list.set_class(pane == CHATS, "-active")
        self.query_one("#chat-pane").set_class(pane == MESSAGES, "-active")
        self._update_context()

    def _update_context(self) -> None:
        chat = self.current_chat
        self.status.set_state(context=chat.title if chat else "")

    def _update_banner(self) -> None:
        banner = self.query_one("#compose-banner", Static)
        if self.editing:
            banner.update(Text(f"✎ Редактирование: {shorten(self.editing.text, 60)}   Esc — отмена"))
        elif self.reply_to:
            who = self.reply_to.sender_name
            what = self.reply_to.text or self.reply_to.media_label
            banner.update(Text(f"↩ Ответ {who}: {shorten(what, 60)}   Esc — отмена"))
        banner.set_class(bool(self.editing or self.reply_to), "-visible")

    def _update_header(self) -> None:
        chat = self.current_chat
        header = self.query_one("#chat-header", Static)
        if chat is None:
            header.update("Выберите чат")
            return
        line = Text(no_wrap=True, overflow="ellipsis")
        line.append(chat.title)
        if chat.username:
            line.append(f"  @{chat.username}", style="cyan")
        line.append(f"  · {KIND_NAMES[chat.kind]}", style="dim")
        header.update(line)

    # --- клавиатура ------------------------------------------------------

    async def on_key(self, event) -> None:
        if self.mode is not Mode.NORMAL:
            return
        event.stop()
        event.prevent_default()
        token = token_from_event(event.key, event.character)
        if token == "backspace" and self.parser.prefix:
            self.parser.back()  # шаг назад в окне подсказок
            action = None
        else:
            action = self.parser.feed(token, self.pane)
        self.status.set_state(pending=self.parser.pending)
        self._update_which_key()
        if action is not None:
            await self.dispatch_vim(action)

    def _update_which_key(self) -> None:
        """Показать/спрятать окно подсказок для начатой последовательности."""
        if self._which_key_timer is not None:
            self._which_key_timer.stop()
            self._which_key_timer = None
        prefix = self.parser.prefix
        if not prefix:
            self.which_key.hide()
            return
        if prefix[0] == _LEADER or self.which_key.visible:
            self._show_which_key()
        else:
            self._which_key_timer = self.set_timer(_WHICH_KEY_DELAY, self._show_which_key)

    def _show_which_key(self) -> None:
        self._which_key_timer = None
        prefix = self.parser.prefix
        if prefix:
            self.which_key.show_keys(prefix, self.parser.continuations(self.pane))

    async def dispatch_vim(self, action: Action) -> None:
        handler = getattr(self, f"vim_{action.name}", None)
        if handler is None:
            self.notify_status(f"Действие {action.name!r} не реализовано", error=True)
            return
        try:
            result = handler(action)
            if inspect.isawaitable(result):
                await result
        except BackendError as exc:
            self.notify_status(str(exc), error=True)

    # --- vim: навигация --------------------------------------------------

    async def vim_cursor_down(self, a: Action) -> None:
        if self.pane == CHATS:
            self.chat_list.move(a.count)
        else:
            self.view.move_cursor(a.count)

    async def vim_cursor_up(self, a: Action) -> None:
        if self.pane == CHATS:
            self.chat_list.move(-a.count)
            return
        if self.view.cursor - a.count < 0:
            await self.load_older()
        self.view.move_cursor(-a.count)

    async def vim_cursor_first(self, a: Action) -> None:
        # gg — в начало; 5gg — на пятую строку, как в vim
        index = a.count - 1 if a.has_count else 0
        if self.pane == CHATS:
            self.chat_list.highlighted = min(index, max(0, len(self.chat_list.visible) - 1))
        else:
            self.view.set_cursor(index)

    async def vim_cursor_last(self, a: Action) -> None:
        if self.pane == CHATS:
            count = len(self.chat_list.visible)
            if count:
                self.chat_list.highlighted = min(a.count - 1, count - 1) if a.has_count else count - 1
        else:
            self.view.set_cursor(a.count - 1 if a.has_count else len(self.view.items) - 1)

    async def _page(self, a: Action, fraction: float) -> None:
        if self.pane == CHATS:
            self.chat_list.move(int(self.chat_list.page_size() * fraction) * a.count)
        else:
            step = int(self.view.page_items() * fraction) or (1 if fraction > 0 else -1)
            if self.view.cursor + step * a.count < 0:
                await self.load_older()
            self.view.move_cursor(step * a.count)

    async def vim_half_page_down(self, a: Action) -> None:
        await self._page(a, 0.5)

    async def vim_half_page_up(self, a: Action) -> None:
        await self._page(a, -0.5)

    async def vim_page_down(self, a: Action) -> None:
        await self._page(a, 1)

    async def vim_page_up(self, a: Action) -> None:
        await self._page(a, -1)

    def vim_toggle_pane(self, a: Action) -> None:
        self._set_pane(MESSAGES if self.pane == CHATS and self.current_chat else CHATS)

    def vim_toggle_chat_list(self, a: Action | None = None) -> None:
        self.set_chat_list_hidden(not self.chat_list_hidden)

    def set_chat_list_hidden(self, hidden: bool) -> None:
        if hidden and self.current_chat is None:
            self.notify_status("Сначала откройте чат — иначе нечего показывать", error=True)
            return
        self.chat_list_hidden = hidden
        if hidden:
            self._set_pane(MESSAGES)
        else:
            # Открыли список — значит, хотят в нём что-то выбрать: фокус туда,
            # курсор на текущий чат.
            self.vim_focus_chats(Action("focus_chats"))
        self.notify_status(
            "Список чатов скрыт: h / Tab — показать временно, <C-n> — вернуть" if hidden
            else "Список чатов показан"
        )

    def vim_find_chat(self, a: Action) -> None:
        self.vim_focus_chats(a)
        self._open_cmdline("/")

    def vim_focus_chats(self, a: Action) -> None:
        self._set_pane(CHATS)
        if self.current_chat:
            self.chat_list.select_id(self.current_chat.id)

    def vim_focus_messages(self, a: Action) -> None:
        if self.current_chat:
            self._set_pane(MESSAGES)

    async def vim_open_chat(self, a: Action) -> None:
        chat = self.chat_list.selected
        if chat is not None:
            await self.open_chat(chat)

    async def vim_goto_reply(self, a: Action) -> None:
        msg = self.view.selected
        if msg is None:
            self.notify_status("Сначала откройте чат и выберите сообщение")
            return
        if msg.reply_to_id is None:
            self.notify_status("Выделенное сообщение — не ответ")
            return
        target = msg.reply_to_id
        index = self.view.index_of(target)
        # Исходное старше загруженного — подгружаем историю, пока не найдём.
        for _ in range(_GOTO_REPLY_PAGES):
            oldest = self.view.oldest_id
            if index is not None or self._history_exhausted or oldest is None or target > oldest:
                break
            self.notify_status("Ищу исходное сообщение…")
            await self.load_older()
            index = self.view.index_of(target)
        if index is None:
            self.notify_status("Исходное сообщение не найдено: удалено или слишком далеко", error=True)
            return
        self._set_pane(MESSAGES)
        if self.view.cursor != index:
            self._jump_back.append(msg.id)
            self._jump_forward.clear()  # новый переход обрывает ветку «вперёд», как в vim
        self.view.set_cursor(index)
        self.notify_status(f"К исходному. Назад: C-o / Space b (переходов: {len(self._jump_back)})")

    def vim_jump_back(self, a: Action) -> None:
        self._jump(self._jump_back, self._jump_forward, a.count, "назад")

    def vim_jump_forward(self, a: Action) -> None:
        self._jump(self._jump_forward, self._jump_back, a.count, "вперёд")

    def _jump(self, source: list[int], target: list[int], count: int, label: str) -> None:
        """Шаг по списку переходов: взять id из `source`, текущее — в `target`."""
        moved = 0
        for _ in range(count):
            index = None
            while source and index is None:  # удалённые сообщения пропускаем
                index = self.view.index_of(source.pop())
            if index is None:
                break
            if (current := self.view.selected) is not None:
                target.append(current.id)
            self.view.set_cursor(index)
            moved += 1
        if not moved:
            self.notify_status(f"Дальше {label} переходов нет")
            return
        self._set_pane(MESSAGES)
        self.notify_status(f"Переход {label}. Осталось: {len(source)}")

    def vim_cancel(self, a: Action) -> None:
        if self.chat_list.filter_text:
            self.chat_list.set_filter("")
        self.search_query = ""
        self.notify_status("")

    # --- vim: режимы -----------------------------------------------------

    def vim_insert(self, a: Action | None = None) -> None:
        if self.current_chat is None:
            self.notify_status("Сначала откройте чат (Enter)")
            return
        self._set_pane(MESSAGES)
        self.composer.add_class("-visible")
        self.composer.can_focus = True
        self.composer.focus()
        self._set_mode(Mode.INSERT)

    def _leave_insert(self) -> None:
        self.composer.popup.hide()
        self.composer.can_focus = False
        self.set_focus(None)
        if not self.composer.text and not self.reply_to and not self.editing:
            self.composer.remove_class("-visible")
        self._set_mode(Mode.NORMAL)

    def vim_command_line(self, a: Action) -> None:
        self._open_cmdline(":")

    def vim_search(self, a: Action) -> None:
        self._open_cmdline("/")

    def _open_cmdline(self, kind: str) -> None:
        self.query_one("#cmdbar").add_class("-visible")
        self.query_one("#cmd-prefix", Static).update(kind)
        initial = self.chat_list.filter_text if kind == "/" and self.pane == CHATS else ""
        self.cmdline.open(kind, initial)
        self._set_mode(Mode.COMMAND if kind == ":" else Mode.SEARCH)

    def _close_cmdline(self) -> None:
        self.cmdline.close()
        self.query_one("#cmdbar").remove_class("-visible")
        self.set_focus(None)
        self._set_mode(Mode.NORMAL)

    def vim_help(self, a: Action) -> None:
        self.app.push_screen(HelpScreen())

    def vim_theme(self, a: Action | None = None) -> None:
        def chosen(name: str | None) -> None:
            if name is not None:
                self.set_theme(name)

        self.app.push_screen(ThemePickerScreen(self.config.ui.theme), chosen)

    def set_theme(self, name: str) -> None:
        """Применить тему и запомнить её в config.toml."""
        apply_theme(self.app, name)
        try:
            save_theme(self.config, name)
        except (OSError, ConfigError) as exc:
            log.exception("save theme")
            self.config.ui.theme = name
            self.notify_status(f"Тема включена, но не сохранена: {exc}", error=True)
            return
        self.notify_status(f"Тема: {SPECS[name].title}")

    async def vim_quit(self, a: Action | None = None) -> None:
        await self.app.shutdown()

    # --- vim: действия с сообщениями ------------------------------------

    # --- vim: реакции ------------------------------------------------------

    async def vim_react(self, a: Action | None = None, query: str = "") -> None:
        msg, chat = self.view.selected, self.current_chat
        if msg is None or chat is None:
            self.notify_status("Сначала откройте чат и выберите сообщение")
            return
        available = await self.backend.get_available_reactions(chat.id)
        if not available:
            self.notify_status("В этом чате реакции выключены", error=True)
            return
        chosen = {r.emoji for r in msg.reactions if r.chosen}
        if a is not None and a.arg:  # Space l c — конкретная реакция из меню
            if a.arg not in available:
                self.notify_status(f"Реакция {reaction_name(a.arg)} в этом чате запрещена", error=True)
                return
            await self._toggle_reaction(chat, msg, a.arg, chosen)
            return
        if query:  # :react clown — без окна
            found = filter_reactions(available, query)
            if not found:
                self.notify_status(f"Нет такой реакции: {query}", error=True)
                return
            await self._toggle_reaction(chat, msg, found[0], chosen)
            return

        def picked(emoji: str | None) -> None:
            if emoji is not None:
                self.run_worker(self._toggle_reaction(chat, msg, emoji, chosen), group="reactions")

        self.app.push_screen(ReactionPickerScreen(available, chosen), picked)

    async def vim_unreact(self, a: Action | None = None) -> None:
        msg, chat = self.view.selected, self.current_chat
        if msg is None or chat is None:
            self.notify_status("Сначала откройте чат и выберите сообщение")
            return
        mine = next((r.emoji for r in msg.reactions if r.chosen), None)
        if mine is None:
            self.notify_status("Вы не ставили реакцию на это сообщение")
            return
        await self._toggle_reaction(chat, msg, mine, {mine})

    async def _toggle_reaction(self, chat: Chat, msg: Message, emoji: str, chosen: set[str]) -> None:
        """Поставить реакцию; если она уже моя — снять."""
        remove = emoji in chosen
        try:
            updated = await self.backend.send_reaction(chat.id, msg.id, None if remove else emoji)
        except BackendError as exc:
            self.notify_status(str(exc), error=True)
            return
        self.view.update_message(updated)
        verb = "снята" if remove else "поставлена"
        self.notify_status(f"Реакция {reaction_name(emoji)} {verb}")
        if self.view.selected is not None and self.view.selected.id == updated.id:
            self._schedule_reaction_users(updated)

    @on(MessageView.Selected)
    def _on_message_selected(self, event: MessageView.Selected) -> None:
        self._schedule_reaction_users(event.message)

    def _schedule_reaction_users(self, msg: Message) -> None:
        if not msg.reactions_incomplete:
            return
        key = (msg.chat_id, msg.id, tuple((r.emoji, r.count) for r in msg.reactions))
        if key in self._reaction_users_loaded:
            return
        # Функция, а не готовая корутина: эксклюзивный воркер отменяет прежний
        # ещё до старта, и созданная заранее корутина осталась бы незапущенной.
        self.run_worker(
            functools.partial(self._load_reaction_users, msg, key),
            group="reaction-users", exclusive=True,
        )

    async def _load_reaction_users(self, msg: Message, key: tuple) -> None:
        await asyncio.sleep(_REACTION_USERS_DELAY)
        try:
            reactions = await self.backend.get_reaction_users(msg.chat_id, msg.id)
        except BackendError as exc:
            log.debug("reaction users: %s", exc)
            return
        self._reaction_users_loaded.add(key)
        item = self.view.item_for(msg.id)
        if item is None or not reactions:
            return
        item.message.reactions = reactions
        item.update_message(item.message)

    def vim_reply(self, a: Action) -> None:
        msg = self.view.selected
        if msg is None:
            self.notify_status("Сначала откройте чат и выберите сообщение")
            return
        self.editing = None
        self.reply_to = msg
        self._update_banner()
        self.vim_insert()

    def vim_edit(self, a: Action) -> None:
        msg = self.view.selected
        if msg is None:
            return
        if not msg.outgoing:
            self.notify_status("Можно редактировать только свои сообщения", error=True)
            return
        self.reply_to = None
        self.editing = msg
        mentions = [
            Mention(label=msg.text[e.offset:e.end], user_id=e.user_id, by_username=False)
            for e in msg.entities
            if e.kind == EntityKind.MENTION_NAME and e.user_id is not None
        ]
        self.composer.set_content(msg.text, mentions)
        self._update_banner()
        self.vim_insert()

    def vim_delete(self, a: Action) -> None:
        msg = self.view.selected
        chat = self.current_chat
        if msg is None or chat is None:
            return

        async def confirmed(ok: bool | None) -> None:
            if not ok:
                return
            try:
                await self.backend.delete_messages(chat.id, [msg.id])
            except BackendError as exc:
                self.notify_status(str(exc), error=True)
                return
            await self.view.remove_ids([msg.id])
            self.notify_status("Сообщение удалено")

        what = shorten(msg.text or msg.media_label, 50)
        self.app.push_screen(ConfirmScreen(f"Удалить сообщение «{what}» у всех?"), confirmed)

    def vim_yank(self, a: Action) -> None:
        msg = self.view.selected
        if msg is None or not msg.text:
            return
        copy_to_clipboard(self.app, msg.text)
        self.notify_status(f"Скопировано: {shorten(msg.text, 40)}")

    def _profile_target(self) -> int | None:
        if self.pane == CHATS:
            chat = self.chat_list.selected
            return chat.id if chat else None
        msg = self.view.selected
        if msg is None:
            return self.current_chat.id if self.current_chat else None
        if msg.is_post or msg.sender_id is None:
            return msg.chat_id
        return msg.sender_id

    def vim_profile(self, a: Action) -> None:
        target = self._profile_target()
        if target is not None:
            self.app.push_screen(ProfileScreen(self.backend, self.config, target))

    def vim_chat_profile(self, a: Action) -> None:
        if self.current_chat:
            self.app.push_screen(ProfileScreen(self.backend, self.config, self.current_chat.id))

    def vim_my_profile(self, a: Action | None = None) -> None:
        if self.backend.me:
            self.app.push_screen(ProfileScreen(self.backend, self.config, self.backend.me.id))

    async def vim_open_media(self, a: Action) -> None:
        msg = self.view.selected
        if msg is None or msg.media is None:
            return
        if msg.has_animation:
            await self._open_animation(msg)
            return
        if not msg.has_image:
            self.notify_status(f"Просмотр «{msg.media_label}» пока не поддерживается")
            return
        item = self.view.item_for(msg.id)
        path = item.image_path if item else None
        if path is None:
            self.notify_status("Загрузка картинки…")
            path = await self.backend.download_image(msg)
        if path is not None:
            self.app.push_screen(ImageViewerScreen(path, title=msg.text or msg.media_label))

    async def _open_animation(self, msg: Message) -> None:
        if self.config.ui.animations == "off":
            self.notify_status("Анимации выключены (ui.animations = \"off\")")
            return
        self.notify_status("Загрузка анимации…")
        try:
            # Для полноэкранного просмотра — отдельное декодирование в большем размере.
            animation = await self._decode_animation(msg, max_px=_VIEWER_ANIM_PX, full=True)
        except Exception as exc:
            log.exception("open animation")
            self.notify_status(f"Не удалось открыть: {exc}", error=True)
            return
        if animation is None:
            return
        item = self.view.item_for(msg.id)
        feed_anim = item.animated if item else None
        if feed_anim is not None:
            feed_anim.stop()  # не тратить CPU на ленту под модальным окном

        def resume(_result=None) -> None:
            if feed_anim is not None and feed_anim.is_mounted:
                self.view.set_cursor(self.view.cursor)  # восстановит play() выделенного

        self.notify_status("")
        self.app.push_screen(
            ImageViewerScreen(
                None,
                title=msg.media_label,
                animation=animation,
                prefer_native=self.config.ui.kitty_native_animation,
            ),
            resume,
        )

    def vim_reload_chats(self, a: Action) -> None:
        self.load_chats()

    async def vim_reload_messages(self, a: Action) -> None:
        if self.current_chat:
            await self.open_chat(self.current_chat)

    # --- поиск (n / N) ---------------------------------------------------

    def _search_messages(self, forward: bool) -> None:
        query = self.search_query.casefold()
        if not query or not self.view.items:
            return
        n = len(self.view.items)
        step = 1 if forward else -1
        for i in range(1, n + 1):
            idx = (self.view.cursor + step * i) % n
            msg = self.view.items[idx].message
            if query in msg.text.casefold() or query in msg.sender_name.casefold():
                self.view.set_cursor(idx)
                return
        self.notify_status(f"Не найдено: {self.search_query}", error=True)

    def vim_search_next(self, a: Action) -> None:
        if self.pane == MESSAGES:
            for _ in range(a.count):
                self._search_messages(True)

    def vim_search_prev(self, a: Action) -> None:
        if self.pane == MESSAGES:
            for _ in range(a.count):
                self._search_messages(False)

    # --- аватарки в списке чатов ---------------------------------------

    @on(ChatList.AvatarsWanted)
    def _on_chat_avatars_wanted(self, event: ChatList.AvatarsWanted) -> None:
        if not images_enabled():
            return  # остаются инициалы
        for chat in event.chats:
            if chat.kind != ChatKind.SAVED:  # у «Избранного» значок, а не своё фото
                self.run_worker(self._load_chat_avatar(chat.id), group="avatars")

    @on(MessageView.AvatarsWanted)
    def _on_sender_avatars_wanted(self, event: MessageView.AvatarsWanted) -> None:
        if not images_enabled():
            return
        for sender_id in event.sender_ids:
            self.run_worker(self._load_sender_avatar(sender_id), group="avatars")

    async def _load_chat_avatar(self, chat_id: int) -> None:
        if (path := await self._small_avatar(chat_id)) is not None:
            self.chat_list.set_avatar(chat_id, path)

    async def _load_sender_avatar(self, sender_id: int) -> None:
        if (path := await self._small_avatar(sender_id)) is not None:
            self.view.set_avatar(sender_id, path)

    async def _small_avatar(self, peer_id: int) -> Path | None:
        """Маленькая аватарка с кэшем; одновременные запросы одного id — одна загрузка."""
        if peer_id in self._avatars:
            return self._avatars[peer_id]
        task = self._avatar_tasks.get(peer_id)
        if task is None:
            task = asyncio.ensure_future(self._download_small_avatar(peer_id))
            self._avatar_tasks[peer_id] = task
        return await asyncio.shield(task)

    async def _download_small_avatar(self, peer_id: int) -> Path | None:
        async with self._avatar_sem:
            try:
                path = await self.backend.download_avatar(peer_id, big=False)
            except Exception as exc:
                log.warning("Аватарка %s не загружена: %s", peer_id, exc)
                path = None
        self._avatars[peer_id] = path
        self._avatar_tasks.pop(peer_id, None)
        return path

    # --- командная строка -----------------------------------------------

    @on(CommandLine.Edited)
    def _on_cmd_edited(self, event: CommandLine.Edited) -> None:
        # После закрытия строки приходит Edited с пустым значением — игнорируем.
        if self.mode is Mode.SEARCH and event.kind == "/" and self.pane == CHATS:
            self.chat_list.set_filter(event.value)

    @on(CommandLine.Finished)
    async def _on_cmd_finished(self, event: CommandLine.Finished) -> None:
        self._close_cmdline()
        if event.kind == "/":
            if self.pane == CHATS:
                self.chat_list.set_filter(event.value or "")
            elif event.value:
                self.search_query = event.value
                self._search_messages(forward=False)
            return
        if event.value:
            try:
                await self.run_command(event.value.strip())
            except BackendError as exc:
                self.notify_status(str(exc), error=True)

    async def run_command(self, line: str) -> None:
        """Команды «:». Список — в docs/KEYBINDINGS.md."""
        if line.isdigit():  # :42 — перейти к строке 42
            await self.dispatch_vim(Action("cursor_first", count=int(line), has_count=True))
            return
        cmd, _, arg = line.partition(" ")
        arg = arg.strip()
        match cmd:
            case "q" | "q!" | "qa" | "quit" | "wq" | "x":
                await self.vim_quit()
            case "o" | "open" | "chat" | "b":
                await self._command_open(arg)
            case "profile" | "info":
                if arg == "me" and self.backend.me:
                    self.vim_my_profile()
                else:
                    self.vim_chat_profile(Action("chat_profile"))
            case "read":
                if self.current_chat and self.view.items:
                    await self._mark_read(self.current_chat, self.view.items[-1].message.id)
            case "reload" | "e":
                self.load_chats()
                if self.current_chat:
                    await self.open_chat(self.current_chat)
            case "help" | "h":
                self.vim_help(Action("help"))
            case "sidebar" | "sb":
                match arg:
                    case "" | "toggle":
                        self.vim_toggle_chat_list()
                    case "on" | "show":
                        self.set_chat_list_hidden(False)
                    case "off" | "hide":
                        self.set_chat_list_hidden(True)
                    case _:
                        self.notify_status(":sidebar [on|off|toggle]", error=True)
            case "react" | "reaction":
                await self.vim_react(query=arg)
            case "theme" | "colorscheme" | "colo":
                if not arg:
                    self.vim_theme()
                elif arg in THEMES:
                    self.set_theme(arg)
                else:
                    self.notify_status(f":theme {'|'.join(THEMES)}", error=True)
            case "nohl" | "noh":
                self.vim_cancel(Action("cancel"))
            case _:
                self.notify_status(f"Неизвестная команда: {cmd}", error=True)

    async def _command_open(self, query: str) -> None:
        if not query:
            self.notify_status(":open <часть названия чата>", error=True)
            return
        q = query.casefold().lstrip("@")
        for chat in self.chat_list.chats:
            if q in chat.title.casefold() or q == (chat.username or "").casefold():
                self.chat_list.set_filter("")
                self.chat_list.select_id(chat.id)
                await self.open_chat(chat)
                return
        self.notify_status(f"Чат не найден: {query}", error=True)

    # --- ввод сообщения --------------------------------------------------

    @on(Composer.Cancelled)
    def _on_composer_cancelled(self) -> None:
        if self.attachment is not None:
            self.set_attachment(None)
            self.notify_status("Вложение убрано")
        if self.reply_to or self.editing:
            was_editing = self.editing is not None
            self.reply_to = self.editing = None
            self._update_banner()
            if was_editing:
                self.composer.reset()
        self._leave_insert()

    # --- вставка из буфера обмена (Ctrl+V) --------------------------------

    @on(Composer.PasteRequested)
    def _on_paste_requested(self) -> None:
        self.run_worker(self._paste_from_clipboard(), group="paste", exclusive=True)

    def vim_paste(self, a: Action | None = None) -> None:
        """Ctrl+V в NORMAL: открыть поле ввода и вставить буфер."""
        if self.current_chat is None:
            self.notify_status("Сначала откройте чат (Enter)")
            return
        self.vim_insert()
        self._on_paste_requested()

    async def _paste_from_clipboard(self) -> None:
        try:
            content = await clipboard.read_clipboard(self.config.media_dir / "outgoing")
        except clipboard.ClipboardError as exc:
            self.notify_status(f"Буфер обмена: {exc}", error=True)
            return
        if content.image is not None:
            if self.editing is not None:
                self.notify_status("При редактировании фото не вложить", error=True)
                return
            self.set_attachment(content.image)
        elif content.text:
            self.composer.insert(content.text)
        else:
            self.notify_status("Буфер обмена пуст")

    def set_attachment(self, path: Path | None) -> None:
        """Показать (или убрать) вложение над полем ввода."""
        box = self.query_one("#attachment")
        for old in box.query("#attachment-preview"):
            old.remove()
        self.attachment = path
        self.composer.has_attachment = path is not None
        box.set_class(path is not None, "-visible")
        if path is None:
            return
        try:
            with PILImage.open(path) as img:
                size = f"{img.width}×{img.height}"
        except Exception as exc:
            self.set_attachment(None)
            self.notify_status(f"В буфере не картинка: {exc}", error=True)
            return
        kb = path.stat().st_size / 1024
        weight = f"{kb / 1024:.1f} МБ" if kb >= 1024 else f"{kb:.0f} КБ"
        label = Text()
        label.append("📎 Фото ", style="bold")
        label.append(f"{size}, {weight}\n")
        label.append("Enter — отправить (текст станет подписью), Ctrl+V — заменить, Esc — убрать",
                     style="dim")
        self.query_one("#attachment-label", Static).update(label)
        if images_enabled():
            preview = make_image(path, fallback="")
            preview.id = "attachment-preview"
            box.mount(preview, before=0)
        self.notify_status("")

    @on(Composer.QueryChanged)
    def _on_mention_query(self, event: Composer.QueryChanged) -> None:
        if event.query is None or self.current_chat is None:
            self.composer.popup.hide()
            return
        self._search_mentions(self.current_chat.id, event.query.query)

    @work(exclusive=True, group="mentions")
    async def _search_mentions(self, chat_id: int, query: str) -> None:
        await asyncio.sleep(_MENTION_DEBOUNCE)
        try:
            users = await self.backend.search_members(chat_id, query)
        except BackendError as exc:
            self.notify_status(str(exc), error=True)
            return
        except Exception:
            log.exception("search_members")
            return
        me = self.backend.me
        users = [u for u in users if me is None or u.id != me.id]
        current = self.composer._query
        if current is not None and current.query == query and self.mode is Mode.INSERT:
            self.composer.popup.show_users(users)

    @on(Composer.Submitted)
    async def _on_submit(self, event: Composer.Submitted) -> None:
        chat = self.current_chat
        if chat is None:
            return
        try:
            if self.editing is not None:
                msg = await self.backend.edit_message(chat.id, self.editing.id, event.text, event.mentions)
                self.view.update_message(msg)
            elif self.attachment is not None:
                reply_id = self.reply_to.id if self.reply_to else None
                self.notify_status("Отправка фото…")
                msg = await self.backend.send_photo(
                    chat.id, self.attachment, event.text, event.mentions, reply_id
                )
                self.set_attachment(None)
                self.notify_status("")
                await self._show_new_message(msg)
            else:
                reply_id = self.reply_to.id if self.reply_to else None
                msg = await self.backend.send_message(chat.id, event.text, event.mentions, reply_id)
                await self._show_new_message(msg)
        except BackendError as exc:
            self.notify_status(str(exc), error=True)
            return
        except Exception as exc:
            log.exception("send")
            self.notify_status(f"Ошибка отправки: {exc}", error=True)
            return
        self.composer.reset()
        self.reply_to = self.editing = None
        self._update_banner()

    # --- загрузка данных -------------------------------------------------

    @work(exclusive=True, group="chats")
    async def load_chats(self) -> None:
        self.notify_status("Загрузка чатов…")
        try:
            chats = await self.backend.get_chats(self.config.ui.dialogs_limit)
        except Exception as exc:
            log.exception("get_chats")
            self.notify_status(f"Не удалось загрузить чаты: {exc}", error=True)
            return
        self.chat_list.set_chats(chats)
        self.notify_status(f"Чатов: {len(chats)}")

    async def open_chat(self, chat: Chat) -> None:
        self.current_chat = chat
        self.reply_to = self.editing = None
        self._history_exhausted = False
        self._jump_back.clear()
        self._jump_forward.clear()
        self.set_attachment(None)  # вложение не переезжает в другой чат
        self.composer.reset()
        self.composer.remove_class("-visible")
        self._update_banner()
        self._update_header()
        self._set_pane(MESSAGES)
        self.view.show_avatars = self.config.ui.message_avatars and chat.kind == ChatKind.GROUP
        await self.view.set_messages([], empty_text="Загрузка…")
        try:
            messages = await self.backend.get_messages(chat.id, self.config.ui.history_limit)
        except BackendError as exc:
            self.notify_status(str(exc), error=True)
            return
        if self.current_chat is not chat:  # пока грузили, открыли другой чат
            return
        await self.view.set_messages(messages)
        self._schedule_images(self.view.items)
        if messages:
            await self._mark_read(chat, messages[-1].id)
        self.notify_status("")

    async def load_older(self) -> None:
        chat = self.current_chat
        if chat is None or self._loading_history or self._history_exhausted:
            return
        oldest = self.view.oldest_id
        if oldest is None:
            return
        self._loading_history = True
        self.notify_status("Загрузка истории…")
        try:
            older = await self.backend.get_messages(chat.id, self.config.ui.history_limit, before_id=oldest)
            if self.current_chat is not chat:
                return
            if not older:
                self._history_exhausted = True
                self.notify_status("Это начало истории")
                return
            items = await self.view.prepend_messages(older)
            self._schedule_images(items)
            self.notify_status("")
        finally:
            self._loading_history = False

    async def _mark_read(self, chat: Chat, max_id: int) -> None:
        if not chat.unread_count and not chat.unread_mentions:
            return
        try:
            await self.backend.mark_read(chat.id, max_id)
        except Exception:
            log.exception("mark_read")
            return
        chat.unread_count = chat.unread_mentions = 0
        self.chat_list.refresh_chat(chat.id)

    # --- картинки --------------------------------------------------------

    def _schedule_images(self, items: list[MessageItem]) -> None:
        if not images_enabled():
            return
        # Сначала самые свежие — они на экране.
        for item in reversed(items):
            if item.message.has_image and item.image_path is None:
                self.run_worker(self._load_image(item), group="images")
            elif item.message.has_animation and item.animated is None:
                self.run_worker(self._load_animation(item), group="images")

    async def _decode_animation(self, message: Message, *, max_px: int, full: bool) -> Animation | None:
        path = await self.backend.download_animation(message)
        if path is None:
            return None
        # Декодирование (PyAV / rlottie) — CPU, в отдельном потоке.
        max_frames = DEFAULT_MAX_FRAMES if full else 1
        return await asyncio.to_thread(load_animation, path, max_px=max_px, max_frames=max_frames)

    async def _load_animation(self, item: MessageItem) -> None:
        ui = self.config.ui
        async with self._image_sem:
            if not item.is_mounted:
                return
            try:
                animation = await self._decode_animation(
                    item.message, max_px=_FEED_ANIM_PX, full=ui.animations == "selected"
                )
            except Exception as exc:
                log.exception("load_animation")
                if item.is_mounted:
                    item.set_image_error(str(exc))
                return
        if animation is None or not item.is_mounted:
            return
        height = ui.sticker_height if item.message.media == MediaKind.STICKER else ui.image_height
        anim = item.set_animation(animation, height=height, prefer_native=ui.kitty_native_animation)
        if self.view.autoplay_selected and self.view.selected is item.message:
            anim.play()

    async def _load_image(self, item: MessageItem) -> None:
        async with self._image_sem:
            if not item.is_mounted:
                return
            try:
                path = await self.backend.download_image(item.message)
            except Exception as exc:
                log.exception("download_image")
                if item.is_mounted:
                    item.set_image_error(str(exc))
                return
        if path is not None and item.is_mounted:
            item.set_image(path)

    # --- события Telegram ------------------------------------------------

    async def handle_backend_event(self, event: BackendEvent) -> None:
        match event:
            case NewMessageEvent(message=msg):
                await self._on_new_message(msg)
            case MessageEditedEvent(message=msg):
                if self.current_chat and msg.chat_id == self.current_chat.id:
                    old = self.view.item_for(msg.id)
                    if old is not None:
                        _keep_known_reactors(old.message, msg)
                    self.view.update_message(msg)
                    selected = self.view.selected
                    if selected is not None and selected.id == msg.id:
                        self._schedule_reaction_users(msg)
            case MessagesDeletedEvent(chat_id=chat_id, message_ids=ids):
                if self.current_chat and chat_id in (None, self.current_chat.id):
                    await self.view.remove_ids(ids)

    async def _show_new_message(self, msg: Message) -> None:
        item = await self.view.append_message(msg)
        if item is not None:
            self._schedule_images([item])
        chat = self.chat_list.get(msg.chat_id)
        if chat is not None:
            chat.last_message = msg.text or f"[{msg.media_label}]"
            chat.last_date = msg.date
            self.chat_list.upsert(chat, to_top=True)

    async def _on_new_message(self, msg: Message) -> None:
        chat = self.chat_list.get(msg.chat_id)
        if chat is None:
            self.load_chats()  # новый диалог
            return
        is_current = self.current_chat is not None and self.current_chat.id == msg.chat_id
        if is_current:
            await self._show_new_message(msg)
            if not msg.outgoing:
                await self._mark_read_now(chat, msg.id)
            return
        if not msg.outgoing:
            chat.unread_count += 1
            if msg.mentions_me:
                chat.unread_mentions += 1
        chat.last_message = msg.text or f"[{msg.media_label}]"
        chat.last_date = msg.date
        self.chat_list.upsert(chat, to_top=True)

    async def _mark_read_now(self, chat: Chat, max_id: int) -> None:
        try:
            await self.backend.mark_read(chat.id, max_id)
        except Exception:
            log.exception("mark_read")


def _keep_known_reactors(old: Message, new: Message) -> None:
    """Обновление сообщения приносит лишь последних поставивших реакции.
    Если счётчик реакции не изменился, оставляем уже догруженный полный список."""
    known = {r.emoji: r for r in old.reactions}
    for r in new.reactions:
        prev = known.get(r.emoji)
        if prev is not None and prev.count == r.count and len(prev.users) > len(r.users):
            r.users = list(prev.users)


def copy_to_clipboard(app, text: str) -> None:
    """Скопировать в буфер: wl-copy под Wayland, иначе OSC 52 (foot и kitty умеют)."""
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        try:
            subprocess.run(["wl-copy"], input=text.encode(), check=True, timeout=2)
            return
        except (OSError, subprocess.SubprocessError):
            log.exception("wl-copy")
    app.copy_to_clipboard(text)
