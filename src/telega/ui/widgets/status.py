"""Нижняя строка (режим, набранные клавиши, сообщения) и командная строка."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.message import Message as TMessage
from textual.widgets import Input, Static

from telega.vim import Mode

_MODE_STYLES = {
    Mode.NORMAL: "bold reverse blue",
    Mode.INSERT: "bold reverse green",
    Mode.COMMAND: "bold reverse yellow",
    Mode.SEARCH: "bold reverse magenta",
}


class StatusLine(Static):
    DEFAULT_CSS = """
    StatusLine {
        height: 1;
        background: $panel;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.mode = Mode.NORMAL
        self.pending = ""
        self.context = ""
        self.note = ""
        self.note_style = ""

    def set_state(self, *, mode: Mode | None = None, pending: str | None = None,
                  context: str | None = None) -> None:
        if mode is not None:
            self.mode = mode
        if pending is not None:
            self.pending = pending
        if context is not None:
            self.context = context
        self._redraw()

    def notify_text(self, text: str, *, error: bool = False) -> None:
        self.note = text
        self.note_style = "bold red" if error else ""
        self._redraw()

    def _redraw(self) -> None:
        line = Text(no_wrap=True, overflow="ellipsis")
        line.append(f" {self.mode.value} ", style=_MODE_STYLES[self.mode])
        line.append(" ")
        if self.context:
            line.append(self.context, style="bold")
            line.append("  ")
        if self.note:
            line.append(self.note, style=self.note_style)
        width = self.size.width or 80
        if self.pending:
            pad = width - line.cell_len - len(self.pending) - 1
            line.append(" " * max(1, pad))
            line.append(self.pending, style="bold")
        self.update(line)

    def on_resize(self) -> None:
        self._redraw()


class CommandLine(Input):
    """Строка «:команда» / «/поиск». Показывается только в этих режимах."""

    DEFAULT_CSS = """
    /* &:focus обязателен: у Input в фокусе своя рамка (border: tall), она
       сильнее простого селектора и съедает единственную строку — текст не виден. */
    CommandLine, CommandLine:focus {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0;
        background: $surface;
    }
    """

    class Finished(TMessage):
        def __init__(self, kind: str, value: str | None) -> None:
            super().__init__()
            self.kind = kind  # ":" или "/"
            self.value = value  # None — отмена (Esc)

    class Edited(TMessage):
        """Текст поиска изменился — для «живого» фильтра."""

        def __init__(self, kind: str, value: str) -> None:
            super().__init__()
            self.kind = kind
            self.value = value

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.kind = ":"
        self.can_focus = False  # фокус только пока строка открыта
        self.history: dict[str, list[str]] = {":": [], "/": []}
        self._history_pos = 0

    def open(self, kind: str, initial: str = "") -> None:
        self.kind = kind
        self.value = initial
        self._history_pos = len(self.history[kind])
        self.can_focus = True
        self.focus()
        self.cursor_position = len(initial)

    def close(self) -> None:
        self.can_focus = False
        self.value = ""

    async def _on_key(self, event: events.Key) -> None:
        key = event.key
        if key == "escape":
            event.stop()
            self.post_message(self.Finished(self.kind, None))
            return
        if key == "enter":
            event.stop()
            value = self.value
            if value and (not self.history[self.kind] or self.history[self.kind][-1] != value):
                self.history[self.kind].append(value)
            self.post_message(self.Finished(self.kind, value))
            return
        if key == "backspace" and not self.value:
            event.stop()
            self.post_message(self.Finished(self.kind, None))
            return
        if key in ("up", "down"):
            event.stop()
            items = self.history[self.kind]
            if items:
                step = -1 if key == "up" else 1
                self._history_pos = max(0, min(len(items), self._history_pos + step))
                self.value = items[self._history_pos] if self._history_pos < len(items) else ""
                self.cursor_position = len(self.value)
            return
        await super()._on_key(event)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.post_message(self.Edited(self.kind, self.value))
