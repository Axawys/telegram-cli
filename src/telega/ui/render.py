"""Превращение моделей в Rich Text — чистые функции, удобно тестировать."""

from __future__ import annotations

from datetime import datetime

from rich.style import Style
from rich.text import Text

from telega.models import Chat, ChatKind, EntityKind, Message

# Стили сущностей. Цвета берутся из переменных темы там, где это возможно
# (см. styles.tcss); здесь — то, что Rich умеет сам.
ENTITY_STYLES: dict[EntityKind, str] = {
    EntityKind.MENTION: "bold cyan",
    EntityKind.MENTION_NAME: "bold cyan",
    EntityKind.HASHTAG: "magenta",
    EntityKind.CASHTAG: "magenta",
    EntityKind.BOT_COMMAND: "bright_blue",
    EntityKind.URL: "underline bright_blue",
    EntityKind.TEXT_URL: "underline bright_blue",
    EntityKind.EMAIL: "underline bright_blue",
    EntityKind.PHONE: "underline",
    EntityKind.BOLD: "bold",
    EntityKind.ITALIC: "italic",
    EntityKind.UNDERLINE: "underline",
    EntityKind.STRIKE: "strike",
    EntityKind.CODE: "reverse",
    EntityKind.PRE: "reverse",
    EntityKind.SPOILER: "reverse dim",
    EntityKind.BLOCKQUOTE: "italic dim",
}

KIND_ICONS: dict[ChatKind, str] = {
    ChatKind.USER: " ",
    ChatKind.BOT: "🤖",
    ChatKind.GROUP: "👥",
    ChatKind.CHANNEL: "📢",
    ChatKind.SAVED: "🔖",
}


KIND_NAMES: dict[ChatKind, str] = {
    ChatKind.USER: "пользователь",
    ChatKind.BOT: "бот",
    ChatKind.GROUP: "группа",
    ChatKind.CHANNEL: "канал",
    ChatKind.SAVED: "избранное",
}


def message_body(message: Message, my_username: str | None = None) -> Text:
    """Текст сообщения с подсветкой сущностей (теги, ссылки, форматирование)."""
    text = Text(message.text)
    for ent in message.entities:
        style = ENTITY_STYLES.get(ent.kind)
        if not style:
            continue
        if ent.kind == EntityKind.TEXT_URL and ent.url:
            style = f"{style} link {ent.url}"
        elif ent.kind == EntityKind.URL:
            style = f"{style} link {message.text[ent.offset:ent.end]}"
        text.stylize(Style.parse(style), ent.offset, ent.end)
        if my_username and ent.kind == EntityKind.MENTION:
            if message.text[ent.offset:ent.end].casefold() == f"@{my_username}".casefold():
                text.stylize("reverse", ent.offset, ent.end)
    return text


def format_time(dt: datetime, time_format: str, date_format: str, now: datetime | None = None) -> str:
    local = dt.astimezone()
    now = (now or datetime.now()).astimezone()
    if local.date() == now.date():
        return local.strftime(time_format)
    return local.strftime(f"{date_format} {time_format}")


def chat_line(chat: Chat, width: int, time_format: str = "%H:%M") -> Text:
    """Строка в списке чатов: иконка, название, счётчики."""
    line = Text(no_wrap=True, overflow="ellipsis")
    line.append(KIND_ICONS.get(chat.kind, " ") + " ")
    if chat.pinned:
        line.append("📌")
    badges = Text()
    if chat.unread_mentions:
        badges.append(" @", style="bold yellow")
    if chat.unread_count:
        badges.append(f" {chat.unread_count}", style="dim" if chat.muted else "bold green")
    title_width = max(4, width - line.cell_len - badges.cell_len - 1)
    title = chat.title
    if len(title) > title_width:
        title = title[: title_width - 1] + "…"
    line.append(title, style="bold" if chat.unread_count else "")
    line.append(" " * max(1, width - line.cell_len - badges.cell_len))
    line.append_text(badges)
    return line
