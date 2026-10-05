"""Поле ввода сообщения (INSERT-режим) и подсказки @упоминаний."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.message import Message as TMessage
from textual.widgets import OptionList, TextArea
from textual.widgets.option_list import Option

from telega.mentions import Mention, MentionQuery, apply_completion, find_query
from telega.models import User

# Клавиши, вставляющие перевод строки (Enter отправляет сообщение).
# shift+enter доступен в терминалах с kitty keyboard protocol (kitty, foot).
NEWLINE_KEYS = {"shift+enter", "alt+enter", "ctrl+j"}


class MentionPopup(OptionList, can_focus=False):
    """Список кандидатов для @упоминания. Управляется из Composer."""

    DEFAULT_CSS = """
    MentionPopup {
        display: none;
        height: auto;
        max-height: 8;
        border: round $accent;
        padding: 0;
    }
    MentionPopup.-visible { display: block; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.users: list[User] = []

    @property
    def visible(self) -> bool:
        return self.has_class("-visible")

    def show_users(self, users: list[User]) -> None:
        self.users = users
        if not users:
            self.hide()
            return
        options = []
        for u in users:
            line = Text()
            line.append(u.display_name, style="bold")
            if u.username:
                line.append(f"  @{u.username}", style="cyan")
            if u.is_bot:
                line.append("  бот", style="dim")
            options.append(Option(line, id=str(u.id)))
        self.set_options(options)
        self.highlighted = 0
        self.add_class("-visible")

    def hide(self) -> None:
        self.users = []
        self.remove_class("-visible")
        self.clear_options()

    def move(self, delta: int) -> None:
        if self.users:
            self.highlighted = ((self.highlighted or 0) + delta) % len(self.users)

    @property
    def selected_user(self) -> User | None:
        if self.users and self.highlighted is not None:
            return self.users[self.highlighted]
        return None


class Composer(TextArea):
    """Многострочный ввод.

    Enter — отправить, Shift/Alt+Enter или Ctrl+J — новая строка, Esc — в
    NORMAL-режим. При наборе «@...» просит экран найти участников
    (`QueryChanged`), экран вызывает `popup.show_users()`.
    """

    DEFAULT_CSS = """
    Composer {
        height: auto;
        max-height: 8;
        min-height: 3;
        border: round $panel;
    }
    Composer:focus { border: round $accent; }
    """

    class Submitted(TMessage):
        def __init__(self, text: str, mentions: list[Mention]) -> None:
            super().__init__()
            self.text = text
            self.mentions = mentions

    class Cancelled(TMessage):
        """Esc: выйти в NORMAL-режим."""

    class PasteRequested(TMessage):
        """Ctrl+V: экран читает системный буфер (картинка → вложение, текст → вставка)."""

    class QueryChanged(TMessage):
        def __init__(self, query: MentionQuery | None) -> None:
            super().__init__()
            self.query = query

    def __init__(self, popup: MentionPopup, **kwargs) -> None:
        super().__init__(soft_wrap=True, show_line_numbers=False, tab_behavior="focus", **kwargs)
        self.popup = popup
        # Фокус получает только в INSERT-режиме (включает MainScreen).
        self.can_focus = False
        self.mentions: list[Mention] = []
        self._query: MentionQuery | None = None
        # Есть вложение — Enter отправляет и без текста (фото без подписи).
        self.has_attachment = False

    # --- API для экрана ---

    def set_content(self, text: str, mentions: list[Mention] | None = None) -> None:
        self.text = text
        self.mentions = list(mentions or [])
        self.move_cursor(self.document.end)

    def reset(self) -> None:
        self.text = ""
        self.mentions = []
        self._set_query(None)

    @property
    def cursor_index(self) -> int:
        return self.document.get_index_from_location(self.cursor_location)

    # --- упоминания ---

    def _set_query(self, query: MentionQuery | None) -> None:
        if query == self._query:
            return
        self._query = query
        if query is None:
            self.popup.hide()
        self.post_message(self.QueryChanged(query))

    def _refresh_query(self) -> None:
        self._set_query(find_query(self.text, self.cursor_index))

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._refresh_query()

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        self._refresh_query()

    def accept_completion(self, user: User | None = None) -> bool:
        user = user or self.popup.selected_user
        if user is None or self._query is None:
            return False
        text, cursor, mention = apply_completion(self.text, self._query, user)
        self.mentions.append(mention)
        self.text = text
        self.move_cursor(self.document.get_location_from_index(cursor))
        self._set_query(None)
        return True

    # --- клавиши ---

    async def _on_key(self, event: events.Key) -> None:
        key = event.key
        handled = True
        if key == "ctrl+v":
            # Свой Ctrl+V: TextArea вставляет лишь из внутреннего буфера Textual,
            # а нам нужен системный — и с картинками.
            self.post_message(self.PasteRequested())
        elif self.popup.visible:
            if key in ("tab", "ctrl+n", "down"):
                self.popup.move(1)
            elif key in ("shift+tab", "ctrl+p", "up"):
                self.popup.move(-1)
            elif key == "enter":
                self.accept_completion()
            elif key == "escape":
                self.popup.hide()
            else:
                handled = False
        elif key == "enter":
            text = self.text.strip()
            if text or self.has_attachment:
                self.post_message(self.Submitted(self.text.rstrip(), list(self.mentions)))
        elif key in NEWLINE_KEYS:
            self.insert("\n")
        elif key == "escape":
            self.post_message(self.Cancelled())
        else:
            handled = False

        if handled:
            event.stop()
            event.prevent_default()
            return
        await super()._on_key(event)
