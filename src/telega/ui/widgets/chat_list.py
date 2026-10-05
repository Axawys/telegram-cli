"""Левая панель: список чатов с аватарками.

Каждый чат — строка ChatRow в две строки терминала: слева аватарка 4×2
клетки (примерно квадрат), справа название со счётчиками и последнее
сообщение. Пока аватарка не скачана (или её нет) — инициалы на цветном фоне.

Аватарки грузятся лениво: список сообщает (AvatarsWanted), какие чаты сейчас
видны, а MainScreen качает их через бэкенд и вызывает set_avatar(). Строки не
пересоздаются при новых сообщениях — только переставляются, иначе картинки
мигали бы и заново кодировались (для sixel это дорого).
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message as TMessage
from textual.widgets import Static

from telega.models import Chat, ChatKind
from telega.ui.render import KIND_ICONS
from telega.ui.widgets.avatar import AVATAR_HEIGHT, Avatar

def _title_line(chat: Chat) -> Text:
    line = Text(no_wrap=True, overflow="ellipsis")
    if chat.kind not in (ChatKind.USER, ChatKind.SAVED):
        line.append(KIND_ICONS.get(chat.kind, "") + " ")
    if chat.pinned:
        line.append("📌")
    line.append(chat.title, style="bold" if chat.unread_count else "")
    return line


def _badges(chat: Chat) -> Text:
    badges = Text(no_wrap=True)
    if chat.unread_mentions:
        badges.append(" @", style="bold yellow")
    if chat.unread_count:
        badges.append(f" {chat.unread_count}", style="dim" if chat.muted else "bold green")
    return badges


def _preview(chat: Chat) -> Text:
    return Text(chat.last_message.replace("\n", " "), style="dim", no_wrap=True, overflow="ellipsis")


class ChatRow(Horizontal):
    DEFAULT_CSS = """
    ChatRow { height: 2; }
    ChatRow > Avatar { margin-right: 1; }
    ChatRow > .chat-text { width: 1fr; height: 2; }
    ChatRow .chat-top { height: 1; }
    ChatRow .chat-title { width: 1fr; height: 1; }
    ChatRow .chat-badges { width: auto; height: 1; }
    ChatRow .chat-preview { height: 1; }
    """

    def __init__(self, chat: Chat, *, show_avatar: bool) -> None:
        super().__init__()
        self.chat = chat
        self.show_avatar = show_avatar

    @property
    def avatar_path(self) -> Path | None:
        found = self.query(Avatar)
        return found.first().path if found else None

    def compose(self):
        if self.show_avatar:
            label = "🔖" if self.chat.kind == ChatKind.SAVED else None
            yield Avatar(self.chat.id, self.chat.title, label=label)
        with Vertical(classes="chat-text"):
            with Horizontal(classes="chat-top"):
                yield Static(_title_line(self.chat), classes="chat-title")
                yield Static(_badges(self.chat), classes="chat-badges")
            yield Static(_preview(self.chat), classes="chat-preview")

    def update_chat(self, chat: Chat) -> None:
        self.chat = chat
        if not self.is_mounted:
            return
        self.query_one(".chat-title", Static).update(_title_line(chat))
        self.query_one(".chat-badges", Static).update(_badges(chat))
        self.query_one(".chat-preview", Static).update(_preview(chat))

    def set_avatar(self, path: Path) -> None:
        for avatar in self.query(Avatar):
            avatar.set_image(path)


class ChatList(VerticalScroll, can_focus=False):
    """Список диалогов.

    Не принимает фокус: клавиши обрабатывает MainScreen (vim-диспетчер),
    а здесь только данные и курсор. Поддерживает фильтр по названию («/»).
    """

    DEFAULT_CSS = """
    ChatList {
        width: 34;
        height: 1fr;
        border: none;
        padding: 0;
        scrollbar-size-vertical: 1;
    }
    /* Здесь, а не в ChatRow: DEFAULT_CSS виджета ограничен им самим,
       и селектор с ChatList.-active там не сработал бы. */
    ChatList > ChatRow.-selected { background: $boost; }
    ChatList.-active > ChatRow.-selected { background: $accent 35%; }
    """

    class AvatarsWanted(TMessage):
        """Эти чаты видны, а их аватарки ещё не запрашивались."""

        def __init__(self, chats: list[Chat]) -> None:
            super().__init__()
            self.chats = chats

    def __init__(self, *, show_avatars: bool = True, **kwargs) -> None:
        super().__init__(**kwargs)
        self.show_avatars = show_avatars
        self._chats: list[Chat] = []
        self._visible: list[Chat] = []
        self._rows: dict[int, ChatRow] = {}
        self._filter = ""
        self._highlighted: int | None = None
        self._avatars_requested: set[int] = set()

    # --- данные ---

    @property
    def chats(self) -> list[Chat]:
        return self._chats

    @property
    def visible(self) -> list[Chat]:
        """Чаты после фильтра, в порядке показа (индексы курсора — по нему)."""
        return self._visible

    def set_chats(self, chats: list[Chat]) -> None:
        self._chats = list(chats)
        self._rebuild(keep_id=self.selected.id if self.selected else None)

    def get(self, chat_id: int) -> Chat | None:
        return next((c for c in self._chats if c.id == chat_id), None)

    def upsert(self, chat: Chat, *, to_top: bool = False) -> None:
        """Обновить чат; `to_top` — поднять выше незакреплённых (новое сообщение)."""
        keep = self.selected.id if self.selected else None
        old_pos = next((i for i, c in enumerate(self._chats) if c.id == chat.id), None)
        self._chats = [c for c in self._chats if c.id != chat.id]
        if to_top and not chat.pinned:
            pos = next((i for i, c in enumerate(self._chats) if not c.pinned), len(self._chats))
        elif old_pos is not None:
            pos = old_pos
        else:
            pos = len(self._chats)
        self._chats.insert(pos, chat)
        self._rebuild(keep_id=keep)

    def refresh_chat(self, chat_id: int) -> None:
        chat = self.get(chat_id)
        if chat is not None and chat_id in self._rows:
            self._rows[chat_id].update_chat(chat)

    def set_avatar(self, chat_id: int, path: Path) -> None:
        if (row := self._rows.get(chat_id)) is not None:
            row.set_avatar(path)

    # --- фильтр ---

    @property
    def filter_text(self) -> str:
        return self._filter

    def set_filter(self, text: str) -> None:
        self._filter = text
        self._rebuild(keep_id=None)

    # --- курсор ---

    @property
    def highlighted(self) -> int | None:
        return self._highlighted

    @highlighted.setter
    def highlighted(self, index: int | None) -> None:
        if index is not None and self._visible:
            index = max(0, min(len(self._visible) - 1, index))
        elif not self._visible:
            index = None
        self._highlighted = index
        self._update_cursor()

    @property
    def selected(self) -> Chat | None:
        if self._highlighted is None or self._highlighted >= len(self._visible):
            return None
        return self._visible[self._highlighted]

    def select_id(self, chat_id: int) -> bool:
        for i, chat in enumerate(self._visible):
            if chat.id == chat_id:
                self.highlighted = i
                return True
        return False

    def move(self, delta: int) -> None:
        if self._visible:
            self.highlighted = (self._highlighted or 0) + delta

    def page_size(self) -> int:
        """Сколько чатов помещается на экране."""
        return max(1, self.size.height // AVATAR_HEIGHT)

    # --- отрисовка ---

    def _rebuild(self, keep_id: int | None) -> None:
        query = self._filter.casefold()
        wanted_ids = {c.id for c in self._chats}
        for chat_id in [i for i in self._rows if i not in wanted_ids]:
            self._rows.pop(chat_id).remove()

        # Строки не пересоздаём: новые монтируем, существующие обновляем и
        # переставляем в нужный порядок.
        ordered: list[ChatRow] = []
        new_rows: list[ChatRow] = []
        for chat in self._chats:
            row = self._rows.get(chat.id)
            if row is None:
                row = ChatRow(chat, show_avatar=self.show_avatars)
                self._rows[chat.id] = row
                new_rows.append(row)
            else:
                row.update_chat(chat)
            ordered.append(row)
        if new_rows:
            self.mount_all(new_rows)
        for index, row in enumerate(ordered):
            if index < len(self.children) and self.children[index] is not row:
                self.move_child(row, before=index)

        self._visible = []
        for chat in self._chats:
            matches = not query or query in chat.title.casefold() or query in (chat.username or "").casefold()
            self._rows[chat.id].display = matches
            if matches:
                self._visible.append(chat)

        if keep_id is not None and self.select_id(keep_id):
            return
        self.highlighted = 0 if self._visible else None
        self.scroll_home(animate=False)

    def _update_cursor(self) -> None:
        selected = self.selected
        for chat_id, row in self._rows.items():
            row.set_class(selected is not None and chat_id == selected.id, "-selected")
        if selected is not None and selected.id in self._rows:
            row = self._rows[selected.id]
            self.call_after_refresh(self._scroll_to_row, row)
        self.call_after_refresh(self._request_avatars)

    def _scroll_to_row(self, row: ChatRow) -> None:
        if row.is_mounted:
            self.scroll_to_widget(row, animate=False, center=False)

    def _request_avatars(self) -> None:
        """Попросить аватарки для видимых (на экране) чатов, ещё не запрошенных."""
        if not self.show_avatars or not self.is_mounted:
            return
        top = self.scroll_offset.y
        bottom = top + max(self.size.height, 1)
        wanted: list[Chat] = []
        y = 0
        for chat in self._visible:
            if y >= bottom:
                break
            if y + AVATAR_HEIGHT > top and chat.id not in self._avatars_requested:
                wanted.append(chat)
            y += AVATAR_HEIGHT
        if wanted:
            self._avatars_requested.update(c.id for c in wanted)
            self.post_message(self.AvatarsWanted(wanted))

    def forget_avatar_request(self, chat_id: int) -> None:
        """Аватарку не удалось скачать — разрешить повторный запрос позже."""
        self._avatars_requested.discard(chat_id)

    def watch_scroll_y(self, old: float, new: float) -> None:
        super().watch_scroll_y(old, new)
        self.call_after_refresh(self._request_avatars)

    def on_resize(self) -> None:
        self.call_after_refresh(self._request_avatars)
