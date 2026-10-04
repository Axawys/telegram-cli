"""Окно подсказок после префикса (как which-key в LazyVim).

После <Space> (или g, d, Z …) снизу показываются все клавиши, которыми можно
продолжить последовательность, с описаниями. Окно стоит в общем потоке
раскладки, а не поверх ленты: sixel/kitty-картинки плохо уживаются с
перекрывающими слоями.
"""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from telega.vim import ACTION_HELP, KEY_GROUPS, display_token, parse_sequence

_GROUPS = {parse_sequence(spec): name for spec, name in KEY_GROUPS.items()}


class WhichKey(Static):
    DEFAULT_CSS = """
    WhichKey {
        display: none;
        height: auto;
        max-height: 12;
        border: round $accent;
        border-title-color: $accent;
        padding: 0 1;
    }
    WhichKey.-visible { display: block; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.prefix: tuple[str, ...] = ()
        self.entries: list[tuple[str, str | None]] = []

    @property
    def visible(self) -> bool:
        return self.has_class("-visible")

    def show_keys(self, prefix: tuple[str, ...], entries: list[tuple[str, str | None]]) -> None:
        if not entries:
            self.hide()
            return
        self.prefix = prefix
        self.entries = entries
        title = " ".join(display_token(t) for t in prefix)
        group = _GROUPS.get(prefix)
        self.border_title = f"{title}  {group}" if group else title
        self.border_subtitle = "Esc — отмена, Backspace — назад"
        self._fill()
        self.add_class("-visible")

    def hide(self) -> None:
        self.remove_class("-visible")
        self.prefix = ()
        self.entries = []

    def describe(self, token: str, action: str | None) -> str:
        if action is not None:
            return ACTION_HELP.get(action, action)
        return "+" + _GROUPS.get((*self.prefix, token), "ещё")

    def _fill(self) -> None:
        cells: list[Text] = []
        for token, action in self.entries:
            cell = Text(no_wrap=True, overflow="ellipsis")
            cell.append(display_token(token), style="bold cyan")
            cell.append(" → ", style="dim")
            cell.append(self.describe(token, action), style="bold magenta" if action is None else "")
            cells.append(cell)
        width = max(20, (self.size.width or self.app.size.width) - 4)
        col = min(max(c.cell_len for c in cells) + 3, width)
        ncols = max(1, width // col)
        nrows = -(-len(cells) // ncols)
        table = Table.grid(padding=(0, 3))
        for _ in range(ncols):
            table.add_column(max_width=col)
        # Заполняем по столбцам, как which-key.
        for r in range(nrows):
            table.add_row(*(cells[c * nrows + r] if c * nrows + r < len(cells) else "" for c in range(ncols)))
        self.update(table)

    def on_resize(self) -> None:
        if self.entries:
            self._fill()
