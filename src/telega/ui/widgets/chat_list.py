"""Левая панель: список чатов."""

from __future__ import annotations

from textual.widgets import OptionList
from textual.widgets.option_list import Option

from telega.models import Chat
from telega.ui.render import chat_line


class ChatList(OptionList, can_focus=False):
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
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._chats: list[Chat] = []
        self._visible: list[Chat] = []
        self._filter = ""

    # --- данные ---

    @property
    def chats(self) -> list[Chat]:
        return self._chats

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
        self._rebuild(keep_id=self.selected.id if self.selected else None)

    # --- фильтр ---

    @property
    def filter_text(self) -> str:
        return self._filter

    def set_filter(self, text: str) -> None:
        self._filter = text
        self._rebuild(keep_id=None)

    # --- курсор ---

    @property
    def selected(self) -> Chat | None:
        if self.highlighted is None or not self._visible:
            return None
        if self.highlighted >= len(self._visible):
            return None
        return self._visible[self.highlighted]

    def select_id(self, chat_id: int) -> bool:
        for i, chat in enumerate(self._visible):
            if chat.id == chat_id:
                self.highlighted = i
                return True
        return False

    def move(self, delta: int) -> None:
        if not self._visible:
            return
        current = self.highlighted or 0
        self.highlighted = max(0, min(len(self._visible) - 1, current + delta))

    def page_size(self) -> int:
        return max(1, self.size.height - 1)

    # --- отрисовка ---

    def _rebuild(self, keep_id: int | None) -> None:
        query = self._filter.casefold()
        self._visible = [
            c for c in self._chats
            if not query or query in c.title.casefold() or query in (c.username or "").casefold()
        ]
        width = max(10, (self.size.width or 34) - 2)
        self.set_options(Option(chat_line(c, width), id=str(c.id)) for c in self._visible)
        if keep_id is not None and self.select_id(keep_id):
            return
        self.highlighted = 0 if self._visible else None

    def on_resize(self) -> None:
        self._rebuild(keep_id=self.selected.id if self.selected else None)
