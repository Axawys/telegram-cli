"""Модели данных, независимые от библиотеки Telegram.

UI работает только с этими классами и ничего не знает о Telethon.
Все смещения в `TextEntity` — индексы Python-строки (кодовые точки),
а не UTF-16, как в протоколе Telegram. Конвертация делается в бэкенде
(см. `telega.text`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class ChatKind(StrEnum):
    USER = "user"
    BOT = "bot"
    GROUP = "group"
    CHANNEL = "channel"
    SAVED = "saved"  # «Избранное»


class MediaKind(StrEnum):
    PHOTO = "photo"
    IMAGE = "image"  # картинка, отправленная файлом
    VIDEO = "video"
    GIF = "gif"
    STICKER = "sticker"
    VOICE = "voice"
    AUDIO = "audio"
    DOCUMENT = "document"
    POLL = "poll"
    LOCATION = "location"
    CONTACT = "contact"
    WEBPAGE = "webpage"
    OTHER = "other"


# Медиа, для которых рисуем картинку прямо в ленте.
IMAGE_KINDS = frozenset({MediaKind.PHOTO, MediaKind.IMAGE})
# Медиа, которые показываем анимацией (или первым кадром): GIF и стикеры всех видов.
ANIMATION_KINDS = frozenset({MediaKind.GIF, MediaKind.STICKER})


class EntityKind(StrEnum):
    MENTION = "mention"  # @username
    MENTION_NAME = "mention_name"  # упоминание пользователя без username
    HASHTAG = "hashtag"
    CASHTAG = "cashtag"
    BOT_COMMAND = "bot_command"
    URL = "url"
    TEXT_URL = "text_url"
    EMAIL = "email"
    PHONE = "phone"
    BOLD = "bold"
    ITALIC = "italic"
    UNDERLINE = "underline"
    STRIKE = "strike"
    CODE = "code"
    PRE = "pre"
    SPOILER = "spoiler"
    BLOCKQUOTE = "blockquote"


@dataclass(frozen=True, slots=True)
class TextEntity:
    kind: EntityKind
    offset: int  # индекс в Python-строке
    length: int
    url: str | None = None
    user_id: int | None = None

    @property
    def end(self) -> int:
        return self.offset + self.length


@dataclass(slots=True)
class User:
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str | None = None
    is_bot: bool = False

    @property
    def display_name(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name or (f"@{self.username}" if self.username else str(self.id))


@dataclass(slots=True)
class Chat:
    id: int  # "marked" peer id: >0 пользователь, <0 группа/канал
    title: str
    kind: ChatKind
    username: str | None = None
    unread_count: int = 0
    unread_mentions: int = 0
    last_message: str = ""
    last_date: datetime | None = None
    pinned: bool = False
    muted: bool = False

    @property
    def is_broadcast(self) -> bool:
        """Канал, в который пишут только администраторы."""
        return self.kind == ChatKind.CHANNEL


@dataclass(slots=True)
class Message:
    id: int
    chat_id: int
    date: datetime
    text: str = ""
    sender_id: int | None = None
    sender_name: str = ""
    outgoing: bool = False
    entities: list[TextEntity] = field(default_factory=list)
    media: MediaKind | None = None
    media_label: str = ""  # человекочитаемое описание: «video 0:42», имя файла и т.п.
    reply_to_id: int | None = None
    edited: bool = False
    mentions_me: bool = False
    is_post: bool = False  # пост канала
    grouped_id: int | None = None  # альбом

    @property
    def has_image(self) -> bool:
        return self.media in IMAGE_KINDS

    @property
    def has_animation(self) -> bool:
        return self.media in ANIMATION_KINDS


@dataclass(slots=True)
class Profile:
    id: int
    title: str
    kind: ChatKind
    username: str | None = None
    phone: str | None = None
    about: str = ""
    status: str = ""  # «в сети», «был(а) 5 мин назад», «1234 подписчика»
    members_count: int | None = None
    avatar: Path | None = None  # заполняется отдельно, после загрузки


class PasswordRequired(Exception):
    """Для входа нужен пароль двухфакторной аутентификации."""


class BackendError(Exception):
    """Ошибка, которую можно показать пользователю как есть."""


class InvalidApiCredentials(BackendError):
    """Telegram отверг api_id / api_hash — нужно ввести их заново."""
