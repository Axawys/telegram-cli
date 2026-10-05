"""Маленькая аватарка 4×2 клетки (примерно квадрат): список чатов и лента групп.

Пока картинка не скачана (или фото нет, или графика выключена) — инициалы на
цветном фоне. Цвет — тот же, что у имени отправителя в ленте (color_for).
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.containers import Container
from textual.widgets import Static

from telega.ui.widgets.image import make_image

# Именованные ANSI-цвета, а не hex: их переводит в RGB палитра текущей темы
# (telega/ui/themes.py), так цвета следуют теме и читаются на светлом фоне.
_COLORS = ["red", "green", "yellow", "blue", "magenta", "cyan"]
AVATAR_WIDTH, AVATAR_HEIGHT = 4, 2


def color_for(peer_id: int | None) -> str:
    return _COLORS[abs(peer_id or 0) % len(_COLORS)]


def initials(title: str) -> str:
    """«Павел Дуров» → «ПД», «telega-cli» → «T»."""
    words = [w for w in title.split() if w[:1].isalnum()]
    if not words:
        return title[:1].upper() or "?"
    return "".join(w[0] for w in words[:2]).upper()


def placeholder(peer_id: int | None, label: str) -> Text:
    style = f"bold reverse {color_for(peer_id)}"
    text = Text(no_wrap=True, overflow="crop")
    text.append(label.center(AVATAR_WIDTH)[:AVATAR_WIDTH], style=style)
    text.append("\n")
    text.append(" " * AVATAR_WIDTH, style=style)
    return text


class Avatar(Container):
    DEFAULT_CSS = """
    Avatar { width: 4; height: 2; }
    Avatar > * { width: 4; height: 2; }
    """

    def __init__(self, peer_id: int | None, title: str, *, label: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.peer_id = peer_id
        self.label = label if label is not None else initials(title)
        self.path: Path | None = None

    def compose(self):
        yield Static(placeholder(self.peer_id, self.label), classes="avatar-initials")

    def set_image(self, path: Path) -> None:
        if self.path == path or not self.is_mounted:
            return
        image = make_image(path, fallback="")
        if isinstance(image, Static):  # картинки выключены — остаются инициалы
            return
        self.path = path
        self.remove_children()
        self.mount(image)
