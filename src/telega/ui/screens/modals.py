"""Модальные экраны: профиль, просмотр картинки, справка, подтверждение.

Все закрываются по q / Esc; прокрутка j/k.
"""

from __future__ import annotations

import logging
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from telega.backend import Backend
from telega.config import Config
from telega.models import BackendError, ChatKind, Profile
from telega.ui.render import KIND_NAMES
from telega.media.animation import Animation
from telega.ui.widgets.animated import AnimatedImage, native_supported
from telega.ui.widgets.image import images_enabled, make_image, protocol_name
from telega.ui.themes import SPECS, apply_theme
from telega.vim import ACTION_HELP, DEFAULT_KEYMAP

log = logging.getLogger(__name__)

# Максимальная высота полноэкранной анимации в sixel (см. ImageViewerScreen).
SIXEL_VIEWER_MAX_HEIGHT = 24

_CLOSE = [
    Binding("escape", "close", show=False),
    Binding("q", "close", show=False),
]
_SCROLL = [
    Binding("j", "scroll(1)", show=False),
    Binding("k", "scroll(-1)", show=False),
    Binding("down", "scroll(1)", show=False),
    Binding("up", "scroll(-1)", show=False),
    Binding("ctrl+d", "scroll(10)", show=False),
    Binding("ctrl+u", "scroll(-10)", show=False),
    Binding("g", "scroll_home", show=False),
    Binding("G", "scroll_end", show=False),
]



class _Modal(ModalScreen):
    AUTO_FOCUS = None
    BINDINGS = _CLOSE + _SCROLL

    DEFAULT_CSS = """
    _Modal { align: center middle; }
    _Modal > .box {
        width: 80%;
        max-width: 100;
        height: 80%;
        border: round $accent;
        background: $surface;
        padding: 0 1;
    }
    """

    def action_close(self) -> None:
        self.dismiss(None)

    def _scroller(self) -> VerticalScroll | None:
        found = self.query(VerticalScroll)
        return found.first() if found else None

    def action_scroll(self, lines: int) -> None:
        if scroller := self._scroller():
            scroller.scroll_relative(y=lines, animate=False)

    def action_scroll_home(self) -> None:
        if scroller := self._scroller():
            scroller.scroll_home(animate=False)

    def action_scroll_end(self) -> None:
        if scroller := self._scroller():
            scroller.scroll_end(animate=False)


class ProfileScreen(_Modal):
    """Профиль пользователя/чата с большой аватаркой."""

    DEFAULT_CSS = """
    ProfileScreen #avatar-box { height: auto; align-horizontal: center; margin: 1 0; }
    ProfileScreen .avatar { width: auto; }
    ProfileScreen #profile-info { height: auto; }
    ProfileScreen .muted { color: $text-muted; }
    """

    def __init__(self, backend: Backend, config: Config, peer_id: int) -> None:
        super().__init__()
        self.backend = backend
        self.config = config
        self.peer_id = peer_id

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="box") as box:
            box.border_title = "Профиль"
            box.border_subtitle = "q — закрыть"
            with Center(id="avatar-box"):
                yield Static("загрузка аватарки…", classes="muted", id="avatar-placeholder")
            yield Static("Загрузка…", id="profile-info")

    def on_mount(self) -> None:
        self.load_profile()
        self.load_avatar()

    @work(group="profile")
    async def load_profile(self) -> None:
        try:
            profile = await self.backend.get_profile(self.peer_id)
        except BackendError as exc:
            self.query_one("#profile-info", Static).update(Text(str(exc), style="red"))
            return
        except Exception as exc:
            log.exception("get_profile")
            self.query_one("#profile-info", Static).update(Text(f"Ошибка: {exc}", style="red"))
            return
        self.query_one("#profile-info", Static).update(self._render_profile(profile))

    @work(group="avatar")
    async def load_avatar(self) -> None:
        placeholder = self.query_one("#avatar-placeholder", Static)
        if not images_enabled():
            placeholder.update("[картинки отключены]")
            return
        try:
            path = await self.backend.download_avatar(self.peer_id)
        except Exception as exc:
            log.exception("download_avatar")
            placeholder.update(f"[аватарка не загружена: {exc}]")
            return
        if path is None:
            placeholder.update("[нет аватарки]")
            return
        image = make_image(path, classes="avatar", fallback="[аватарка]")
        image.styles.height = self.config.ui.avatar_height
        await placeholder.remove()
        await self.query_one("#avatar-box").mount(image)

    @staticmethod
    def _render_profile(p: Profile) -> Table:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="dim", justify="right")
        table.add_column()
        table.add_row("", Text(p.title, style="bold"))
        table.add_row("тип", KIND_NAMES.get(p.kind, p.kind.value))
        if p.username:
            table.add_row("username", Text(f"@{p.username}", style="cyan"))
        if p.phone:
            table.add_row("телефон", p.phone)
        if p.status:
            table.add_row("статус", p.status)
        if p.about:
            table.add_row("о себе" if p.kind in (ChatKind.USER, ChatKind.BOT) else "описание", p.about)
        table.add_row("id", str(p.id))
        return table


class ImageViewerScreen(_Modal):
    """Картинка или анимация на весь экран (o / Enter на сообщении с медиа)."""

    DEFAULT_CSS = """
    ImageViewerScreen > .box { width: 100%; height: 100%; max-width: 100%; align: center middle; }
    ImageViewerScreen .viewer-image { width: auto; height: 1fr; }
    ImageViewerScreen .viewer-anim { align: center middle; }
    """

    def __init__(
        self,
        path: Path | None,
        title: str = "",
        *,
        animation: Animation | None = None,
        prefer_native: bool = True,
    ) -> None:
        super().__init__()
        self.path = path
        self.title_text = title
        self.animation = animation
        self.prefer_native = prefer_native
        self.animated: AnimatedImage | None = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="box") as box:
            box.border_title = self.title_text[:60]
            if self.animation is not None:
                box.border_subtitle = "q — закрыть"
                # Высота в строках: экран минус рамка; ширина подстроится по пропорциям.
                height = max(4, self.app.size.height - 4)
                if not native_supported(self.prefer_native) and protocol_name() == "sixel":
                    # Sixel кодируется заново на каждый кадр, время растёт с площадью:
                    # на весь экран (~40 строк) выходит ~4 fps, на 24 строках — ~12.
                    height = min(height, SIXEL_VIEWER_MAX_HEIGHT)
                self.animated = AnimatedImage(
                    self.animation, height=height, prefer_native=self.prefer_native,
                    classes="viewer-anim",
                )
                yield self.animated
            else:
                assert self.path is not None
                box.border_subtitle = f"{self.path.name} · q — закрыть"
                yield make_image(self.path, classes="viewer-image", fallback=str(self.path))

    def on_mount(self) -> None:
        if self.animated is not None:
            self.animated.play()
            self._update_stats()
            self.set_interval(1, self._update_stats)

    def _update_stats(self) -> None:
        if self.animated is not None:
            text = f"{self.animated.describe()} · q — закрыть"
            self.query_one(".box").border_subtitle = text
            log.debug("viewer: %s", text)


class HelpScreen(_Modal):
    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="box") as box:
            box.border_title = "Справка"
            box.border_subtitle = "j/k — прокрутка, q — закрыть"
            yield Static(self._keys_table())

    @staticmethod
    def _keys_table() -> Table:
        titles = {"global": "Везде (NORMAL)", "chats": "Список чатов", "messages": "Сообщения"}
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold cyan", justify="right")
        table.add_column()
        for context, keys in DEFAULT_KEYMAP.items():
            table.add_row("", "")
            table.add_row("", Text(titles.get(context, context), style="bold underline"))
            by_action: dict[str, list[str]] = {}
            for seq, action in keys.items():
                by_action.setdefault(action, []).append(seq)
            for action, seqs in by_action.items():
                table.add_row("  ".join(seqs), ACTION_HELP.get(action, action))
        table.add_row("", "")
        table.add_row("", Text("INSERT", style="bold underline"))
        table.add_row("Enter", "отправить")
        table.add_row("Shift/Alt+Enter, C-j", "новая строка")
        table.add_row("@имя", "подсказка участников: Tab/C-n/↓ дальше, S-Tab/C-p/↑ назад, Enter — выбрать")
        table.add_row("Esc", "в NORMAL (отменяет ответ/редактирование)")
        table.add_row("", "")
        table.add_row("", Text("Команды", style="bold underline"))
        table.add_row(":q  :quit", "выход")
        table.add_row(":open <чат>", "открыть чат по части названия или @username")
        table.add_row(":profile [me]", "профиль текущего чата / свой")
        table.add_row(":read", "отметить прочитанным")
        table.add_row(":reload", "перезагрузить чаты и сообщения")
        table.add_row(":sidebar [on|off]", "скрыть / показать список чатов")
        table.add_row(":theme [имя]", "сменить тему (без имени — окно выбора)")
        table.add_row(":<N>", "перейти на строку N")
        return table


class ConfirmScreen(ModalScreen[bool]):
    """Вопрос да/нет: y/Enter — да, n/Esc/q — нет."""

    AUTO_FOCUS = None
    BINDINGS = [
        Binding("y", "answer(True)", show=False),
        Binding("enter", "answer(True)", show=False),
        Binding("n", "answer(False)", show=False),
        Binding("escape", "answer(False)", show=False),
        Binding("q", "answer(False)", show=False),
    ]
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Static {
        width: auto;
        max-width: 80%;
        border: round $warning;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        yield Static(f"{self.question}\n\n[b]y[/b] — да    [b]n[/b] — нет")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


class ThemePickerScreen(ModalScreen[str | None]):
    """Выбор темы с живым предпросмотром, как colorscheme-пикер в LazyVim.

    j/k — листать (тема сразу применяется), Enter — оставить, Esc/q — вернуть
    прежнюю. Результат — имя темы или None.
    """

    AUTO_FOCUS = "OptionList"
    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("q", "cancel", show=False),
        Binding("j", "move(1)", show=False),
        Binding("k", "move(-1)", show=False),
        Binding("g", "first", show=False),
        Binding("G", "last", show=False),
    ]

    DEFAULT_CSS = """
    ThemePickerScreen { align: right top; }
    ThemePickerScreen > OptionList {
        margin: 1 2;
        width: 40;
        height: auto;
        max-height: 12;
        border: round $accent;
        background: $surface;
        padding: 0 1;
    }
    """

    def __init__(self, current: str) -> None:
        super().__init__()
        self.original = current
        self.names = list(SPECS)

    def compose(self) -> ComposeResult:
        options = []
        for name, spec in SPECS.items():
            label = Text(spec.title)
            if name == self.original:
                label.append("  ●", style="bold")
            options.append(Option(label, id=name))
        picker = OptionList(*options)
        picker.border_title = "Тема"
        picker.border_subtitle = "Enter — выбрать, Esc — отмена"
        yield picker

    def on_mount(self) -> None:
        # Прозрачный фон и окно в углу: при предпросмотре должен быть виден чат.
        # Инлайн-стиль, потому что «Screen { background }» из CSS приложения
        # сильнее DEFAULT_CSS.
        self.styles.background = "transparent"
        self.query_one(OptionList).highlighted = self.names.index(self.original)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id:
            apply_theme(self.app, event.option.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_move(self, step: int) -> None:
        picker = self.query_one(OptionList)
        picker.highlighted = ((picker.highlighted or 0) + step) % len(self.names)

    def action_first(self) -> None:
        self.query_one(OptionList).highlighted = 0

    def action_last(self) -> None:
        self.query_one(OptionList).highlighted = len(self.names) - 1

    def action_cancel(self) -> None:
        apply_theme(self.app, self.original)
        self.dismiss(None)
