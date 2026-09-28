"""Интерфейс бэкенда: всё, что UI может попросить у Telegram.

Реализации:
  TelethonBackend — настоящий Telegram (MTProto через Telethon)
  DemoBackend     — фейковые данные для разработки UI и тестов

UI должен обращаться к Telegram только через этот интерфейс.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from telega.mentions import Mention
from telega.models import Chat, Message, Profile, User


# --- События, которые бэкенд присылает в UI -------------------------------


@dataclass(frozen=True, slots=True)
class NewMessageEvent:
    message: Message


@dataclass(frozen=True, slots=True)
class MessageEditedEvent:
    message: Message


@dataclass(frozen=True, slots=True)
class MessagesDeletedEvent:
    # Для личных чатов и обычных групп Telegram не сообщает, из какого чата
    # удалено сообщение, поэтому chat_id может быть None.
    chat_id: int | None
    message_ids: list[int]


BackendEvent = NewMessageEvent | MessageEditedEvent | MessagesDeletedEvent
EventListener = Callable[[BackendEvent], None]


class Backend(ABC):
    """Асинхронный фасад над Telegram."""

    def __init__(self) -> None:
        self._listeners: list[EventListener] = []
        self.me: User | None = None

    # --- события ---

    def add_listener(self, listener: EventListener) -> None:
        self._listeners.append(listener)

    def _emit(self, event: BackendEvent) -> None:
        for listener in self._listeners:
            listener(event)

    # --- жизненный цикл и авторизация ---

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def is_authorized(self) -> bool: ...

    @abstractmethod
    async def send_code(self, phone: str) -> None: ...

    @abstractmethod
    async def sign_in_code(self, code: str) -> None:
        """Может бросить `PasswordRequired`, если включена 2FA."""

    @abstractmethod
    async def sign_in_password(self, password: str) -> None: ...

    @abstractmethod
    async def load_me(self) -> User:
        """Загрузить текущего пользователя в `self.me` и включить приём событий."""

    # --- данные ---

    @abstractmethod
    async def get_chats(self, limit: int) -> list[Chat]:
        """Диалоги в порядке, как в официальном клиенте (закреплённые сверху)."""

    @abstractmethod
    async def get_messages(
        self, chat_id: int, limit: int, before_id: int | None = None
    ) -> list[Message]:
        """История: от старых к новым. `before_id` — загрузить сообщения старше этого."""

    @abstractmethod
    async def send_message(
        self,
        chat_id: int,
        text: str,
        mentions: list[Mention] | None = None,
        reply_to: int | None = None,
    ) -> Message: ...

    @abstractmethod
    async def edit_message(
        self, chat_id: int, message_id: int, text: str, mentions: list[Mention] | None = None
    ) -> Message: ...

    @abstractmethod
    async def delete_messages(self, chat_id: int, message_ids: list[int]) -> None: ...

    @abstractmethod
    async def mark_read(self, chat_id: int, max_id: int) -> None: ...

    @abstractmethod
    async def search_members(self, chat_id: int, query: str, limit: int = 20) -> list[User]:
        """Кандидаты для автодополнения @упоминаний в чате."""

    # --- медиа и профили ---

    @abstractmethod
    async def download_image(self, message: Message) -> Path | None:
        """Скачать картинку сообщения в кэш и вернуть путь (None — нечего качать)."""

    @abstractmethod
    async def download_animation(self, message: Message) -> Path | None:
        """Скачать GIF / стикер сообщения в кэш (.mp4, .webm, .tgs, .webp)."""

    @abstractmethod
    async def download_avatar(self, peer_id: int) -> Path | None:
        """Скачать аватарку пользователя/чата (большую) и вернуть путь."""

    @abstractmethod
    async def get_profile(self, peer_id: int) -> Profile: ...
