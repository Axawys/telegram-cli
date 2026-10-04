"""Правая панель: лента сообщений с курсором."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from telega.models import Message
from telega.text import shorten
from telega.ui.render import format_time, message_body
from telega.media.animation import Animation
from telega.ui.widgets.animated import AnimatedImage
from telega.ui.widgets.image import make_image

# Именованные ANSI-цвета, а не hex: их переводит в RGB палитра текущей темы
# (telega/ui/themes.py), так имена читаются и на светлом фоне.
_NAME_COLORS = ["red", "green", "yellow", "blue", "magenta", "cyan"]


def _name_color(sender_id: int | None) -> str:
    return _NAME_COLORS[abs(sender_id or 0) % len(_NAME_COLORS)]


class MessageItem(Vertical):
    """Одно сообщение: заголовок, цитата ответа, текст, медиа."""

    DEFAULT_CSS = """
    MessageItem {
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
    }
    MessageItem.-selected {
        background: $boost;
        border-left: thick $accent;
        padding-left: 0;
    }
    MessageItem.-mentions-me {
        border-left: thick $warning;
        padding-left: 0;
    }
    MessageItem .msg-header { height: 1; }
    MessageItem .msg-reply { color: $text-muted; height: 1; }
    MessageItem .msg-body { height: auto; }
    MessageItem .msg-media-label { color: $text-muted; height: 1; }
    MessageItem .msg-image { width: auto; margin-top: 1; }
    MessageItem .msg-anim { margin-top: 1; }
    """

    def __init__(
        self,
        message: Message,
        *,
        reply_text: str | None,
        my_username: str | None,
        time_format: str,
        date_format: str,
        image_height: int,
    ) -> None:
        classes = "-mentions-me" if message.mentions_me else ""
        super().__init__(classes=classes)
        self.message = message
        self._reply_text = reply_text
        self._my_username = my_username
        self._time_format = time_format
        self._date_format = date_format
        self._image_height = image_height
        self.image_path: Path | None = None
        self.animated: AnimatedImage | None = None

    def compose(self):
        yield Static(self._header(), classes="msg-header")
        if self.message.reply_to_id is not None:
            yield Static(self._reply_line(), classes="msg-reply")
        body = Static(self._body(), classes="msg-body")
        body.display = bool(self.message.text)
        yield body
        if self.message.media is not None and self.message.media_label:
            loading = self.message.has_image or self.message.has_animation
            placeholder = "загрузка…" if loading else ""
            label = f"[{self.message.media_label}{' — ' + placeholder if placeholder else ''}]"
            yield Static(label, classes="msg-media-label")

    def _header(self) -> Text:
        m = self.message
        header = Text(no_wrap=True, overflow="ellipsis")
        header.append(m.sender_name or "?", style=f"bold {_name_color(m.sender_id)}")
        header.append("  ")
        header.append(format_time(m.date, self._time_format, self._date_format), style="dim")
        if m.edited:
            header.append("  (изм.)", style="dim italic")
        return header

    def _reply_line(self) -> Text:
        snippet = shorten(self._reply_text or f"сообщение #{self.message.reply_to_id}", 60)
        return Text(f"↳ {snippet}", no_wrap=True, overflow="ellipsis")

    def _body(self) -> Text:
        return message_body(self.message, self._my_username)

    def update_message(self, message: Message) -> None:
        self.message = message
        self.query_one(".msg-header", Static).update(self._header())
        body = self.query_one(".msg-body", Static)
        body.update(self._body())
        body.display = bool(message.text)

    def set_image(self, path: Path) -> None:
        """Показать скачанную картинку вместо подписи «загрузка…»."""
        if self.image_path == path:
            return
        self.image_path = path
        # Подпись «[фото — загрузка…]» больше не нужна — вместо неё картинка.
        for label in self.query(".msg-media-label"):
            label.display = False
        image = make_image(path, classes="msg-image", fallback=f"[{self.message.media_label}]")
        image.styles.height = self._image_height
        self.mount(image)

    def set_animation(self, animation: Animation, *, height: int, prefer_native: bool) -> AnimatedImage:
        """Показать GIF/стикер (первый кадр; play() запускает анимацию)."""
        if self.animated is not None:
            return self.animated
        for label in self.query(".msg-media-label"):
            if animation.animated:
                label.update(Text(f"▶ {self.message.media_label}", style="dim"))
            else:
                label.display = False
        self.animated = AnimatedImage(
            animation, height=height, prefer_native=prefer_native, classes="msg-anim"
        )
        self.mount(self.animated)
        return self.animated

    def set_image_error(self, error: str) -> None:
        for label in self.query(".msg-media-label"):
            label.update(f"[{self.message.media_label} — не загружено: {error}]")


class MessageView(VerticalScroll, can_focus=False):
    """Лента сообщений текущего чата.

    Курсор (выделенное сообщение) нужен для vim-действий: r, e, dd, yy, K, o.
    """

    DEFAULT_CSS = """
    MessageView {
        height: 1fr;
        scrollbar-size-vertical: 1;
    }
    MessageView > .empty {
        color: $text-muted;
        padding: 1 2;
    }
    """

    def __init__(self, *, time_format: str, date_format: str, image_height: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self._time_format = time_format
        self._date_format = date_format
        self._image_height = image_height
        self.my_username: str | None = None
        # Проигрывать анимацию выделенного сообщения (ui.animations = "selected").
        self.autoplay_selected = True
        self.items: list[MessageItem] = []
        self.cursor: int = -1

    # --- построение ---

    def _make_item(self, message: Message, lookup: dict[int, Message]) -> MessageItem:
        reply = lookup.get(message.reply_to_id) if message.reply_to_id else None
        reply_text = None
        if reply is not None:
            reply_text = f"{reply.sender_name}: {reply.text or reply.media_label}"
        return MessageItem(
            message,
            reply_text=reply_text,
            my_username=self.my_username,
            time_format=self._time_format,
            date_format=self._date_format,
            image_height=self._image_height,
        )

    def _lookup(self, extra: list[Message] = ()) -> dict[int, Message]:
        table = {item.message.id: item.message for item in self.items}
        table.update((m.id, m) for m in extra)
        return table

    async def set_messages(self, messages: list[Message], *, empty_text: str = "Нет сообщений") -> None:
        await self.remove_children()
        lookup = self._lookup(messages)
        self.items = [self._make_item(m, lookup) for m in messages]
        if self.items:
            await self.mount_all(self.items)
        else:
            await self.mount(Static(empty_text, classes="empty"))
        self.cursor = len(self.items) - 1
        self._update_cursor(scroll=False)
        self.call_after_refresh(self.scroll_end, animate=False)

    async def prepend_messages(self, messages: list[Message]) -> list[MessageItem]:
        """Добавить более старые сообщения сверху (подгрузка истории)."""
        known = {i.message.id for i in self.items}
        messages = [m for m in messages if m.id not in known]
        if not messages:
            return []
        lookup = self._lookup(messages)
        new_items = [self._make_item(m, lookup) for m in messages]
        if self.items:
            await self.mount_all(new_items, before=self.items[0])
        else:
            await self.remove_children()
            await self.mount_all(new_items)
        self.items = new_items + self.items
        self.cursor += len(new_items)
        return new_items

    async def append_message(self, message: Message) -> MessageItem | None:
        if any(i.message.id == message.id for i in self.items):
            return None
        follow = self.cursor >= len(self.items) - 1
        if not self.items:
            await self.remove_children()
        item = self._make_item(message, self._lookup())
        await self.mount(item)
        self.items.append(item)
        if follow:
            self.cursor = len(self.items) - 1
            self._update_cursor(scroll=False)
            self.call_after_refresh(self.scroll_end, animate=False)
        return item

    def update_message(self, message: Message) -> bool:
        item = self.item_for(message.id)
        if item is None:
            return False
        item.update_message(message)
        return True

    async def remove_ids(self, ids: list[int]) -> None:
        wanted = set(ids)
        doomed = [i for i in self.items if i.message.id in wanted]
        if not doomed:
            return
        selected = self.selected
        self.items = [i for i in self.items if i.message.id not in wanted]
        for item in doomed:
            await item.remove()
        if selected is not None and selected.id in wanted:
            self.cursor = min(self.cursor, len(self.items) - 1)
        elif selected is not None:
            self.cursor = next(
                (n for n, i in enumerate(self.items) if i.message.id == selected.id), -1
            )
        self._update_cursor()

    # --- доступ ---

    def item_for(self, message_id: int) -> MessageItem | None:
        return next((i for i in self.items if i.message.id == message_id), None)

    def index_of(self, message_id: int) -> int | None:
        return next((n for n, i in enumerate(self.items) if i.message.id == message_id), None)

    @property
    def selected(self) -> Message | None:
        if 0 <= self.cursor < len(self.items):
            return self.items[self.cursor].message
        return None

    @property
    def oldest_id(self) -> int | None:
        return self.items[0].message.id if self.items else None

    # --- курсор ---

    def move_cursor(self, delta: int) -> None:
        self.set_cursor(self.cursor + delta)

    def set_cursor(self, index: int) -> None:
        if not self.items:
            return
        self.cursor = max(0, min(len(self.items) - 1, index))
        self._update_cursor()

    def page_items(self) -> int:
        """Примерное число сообщений на экране (для <C-d>/<C-f>)."""
        return max(1, self.size.height // 3)

    def _update_cursor(self, scroll: bool = True) -> None:
        for n, item in enumerate(self.items):
            selected = n == self.cursor
            item.set_class(selected, "-selected")
            if item.animated is not None:
                if selected and self.autoplay_selected:
                    item.animated.play()
                else:
                    item.animated.stop()
        if scroll and 0 <= self.cursor < len(self.items):
            self.scroll_to_widget(self.items[self.cursor], animate=False, center=False)
