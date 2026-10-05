"""Бэкенд на Telethon (MTProto).

Отвечает за конвертацию объектов Telethon в модели `telega.models` — выше
этого файла Telethon-типы не должны протекать.

Работает в том же asyncio-цикле, что и Textual, поэтому никаких потоков:
обработчики событий Telethon вызывают `self._emit`, а UI получает событие
в своём цикле.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient, events, errors, functions, types, utils
from telethon.tl.custom.message import Message as TLMessage

from telega import __version__
from telega.backend.base import (
    Backend,
    MessageEditedEvent,
    MessagesDeletedEvent,
    NewMessageEvent,
)
from telega.config import Config
from telega.mentions import Mention, filter_users, resolve_mentions
from telega.models import (
    BackendError,
    Chat,
    InvalidApiCredentials,
    ChatKind,
    EntityKind,
    MediaKind,
    Message,
    PasswordRequired,
    Profile,
    Reaction,
    TextEntity,
    User,
)
from telega.reactions import CUSTOM_PREFIX, PAID, STANDARD_REACTIONS, normalize
from telega.text import py_to_utf16, utf16_span_to_py

log = logging.getLogger(__name__)

# Telethon-сущность → наш EntityKind
_ENTITY_KINDS: dict[type, EntityKind] = {
    types.MessageEntityMention: EntityKind.MENTION,
    types.MessageEntityMentionName: EntityKind.MENTION_NAME,
    types.InputMessageEntityMentionName: EntityKind.MENTION_NAME,
    types.MessageEntityHashtag: EntityKind.HASHTAG,
    types.MessageEntityCashtag: EntityKind.CASHTAG,
    types.MessageEntityBotCommand: EntityKind.BOT_COMMAND,
    types.MessageEntityUrl: EntityKind.URL,
    types.MessageEntityTextUrl: EntityKind.TEXT_URL,
    types.MessageEntityEmail: EntityKind.EMAIL,
    types.MessageEntityPhone: EntityKind.PHONE,
    types.MessageEntityBold: EntityKind.BOLD,
    types.MessageEntityItalic: EntityKind.ITALIC,
    types.MessageEntityUnderline: EntityKind.UNDERLINE,
    types.MessageEntityStrike: EntityKind.STRIKE,
    types.MessageEntityCode: EntityKind.CODE,
    types.MessageEntityPre: EntityKind.PRE,
    types.MessageEntitySpoiler: EntityKind.SPOILER,
    types.MessageEntityBlockquote: EntityKind.BLOCKQUOTE,
}

# Участников групп до такого размера грузим целиком и фильтруем локально,
# в больших — ищем на сервере по каждому запросу.
_FULL_MEMBERS_LIMIT = 200
_RAW_CACHE_SIZE = 3000
_MAX_PHOTO_UPLOAD = 10 * 1024 * 1024
# Картинки-документы крупнее этого размера не качаем целиком — только превью.
_MAX_IMAGE_DOCUMENT = 8 * 1024 * 1024
# GIF крупнее — не качаем (обычно это длинные ролики).
_MAX_ANIMATION = 20 * 1024 * 1024
# Расширения по MIME: Telethon не всегда угадывает .tgs.
_ANIMATION_EXT = {
    "application/x-tgsticker": ".tgs",
    "video/webm": ".webm",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "image/gif": ".gif",
}


def _reaction_key(reaction) -> str | None:
    """Telethon-реакция → ключ из telega/reactions.py."""
    if isinstance(reaction, types.ReactionEmoji):
        return normalize(reaction.emoticon)
    if isinstance(reaction, types.ReactionCustomEmoji):
        return f"{CUSTOM_PREFIX}{reaction.document_id}"
    if isinstance(reaction, types.ReactionPaid):
        return PAID
    return None


def _user_from_tl(u: types.User) -> User:
    return User(
        id=u.id,
        first_name=u.first_name or "",
        last_name=u.last_name or "",
        username=u.username,
        is_bot=bool(u.bot),
    )


def _format_duration(seconds: float | None) -> str:
    if not seconds:
        return ""
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _format_size(size: int | None) -> str:
    if not size:
        return ""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _format_status(status: types.TypeUserStatus | None) -> str:
    match status:
        case types.UserStatusOnline():
            return "в сети"
        case types.UserStatusOffline(was_online=when):
            return f"был(а) {when.astimezone():%d.%m.%Y %H:%M}"
        case types.UserStatusRecently():
            return "был(а) недавно"
        case types.UserStatusLastWeek():
            return "был(а) на этой неделе"
        case types.UserStatusLastMonth():
            return "был(а) в этом месяце"
    return ""


class TelethonBackend(Backend):
    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        api_id, api_hash = config.require_api_credentials()
        session = config.session_path
        session.parent.mkdir(parents=True, exist_ok=True)
        config.media_dir.mkdir(parents=True, exist_ok=True)
        self._client = TelegramClient(
            str(session),
            api_id,
            api_hash,
            device_model="telega-cli",
            system_version=f"{platform.system()} {platform.release()}",
            app_version=__version__,
            # Не ждать бесконечно: общий потолок задаёт ещё и UI (CONNECT_TIMEOUT).
            connection_retries=3,
            retry_delay=2,
            timeout=10,
            request_retries=3,
            auto_reconnect=True,
        )
        # SQLite-файл сессии создаётся в конструкторе — сразу закрываем доступ.
        session_file = session.with_suffix(".session")
        if session_file.exists():
            os.chmod(session_file, 0o600)
        self._phone: str | None = None
        self._entities: dict[int, types.TypeUser | types.TypeChat] = {}
        # (chat_id, message_id) → сырой Telethon-message; нужен для загрузки медиа
        self._raw: OrderedDict[tuple[int, int], TLMessage] = OrderedDict()
        self._members: dict[int, list[User]] = {}
        self._members_complete: set[int] = set()
        self._handlers_installed = False
        self._available_reactions: dict[int, list[str]] = {}

    # --- жизненный цикл ---------------------------------------------------

    async def connect(self) -> None:
        await self._client.connect()

    async def disconnect(self) -> None:
        await self._client.disconnect()

    async def is_authorized(self) -> bool:
        return await self._client.is_user_authorized()

    async def send_code(self, phone: str) -> None:
        self._phone = phone
        try:
            await self._client.send_code_request(phone)
        except errors.PhoneNumberInvalidError as exc:
            raise BackendError("Неверный номер телефона") from exc
        except errors.ApiIdInvalidError as exc:
            raise InvalidApiCredentials("Telegram не принял api_id / api_hash") from exc
        except errors.FloodWaitError as exc:
            raise BackendError(f"Слишком много попыток, подождите {exc.seconds} с") from exc

    async def sign_in_code(self, code: str) -> None:
        try:
            await self._client.sign_in(self._phone, code)
        except errors.SessionPasswordNeededError as exc:
            raise PasswordRequired from exc
        except (errors.PhoneCodeInvalidError, errors.PhoneCodeExpiredError) as exc:
            raise BackendError("Неверный или просроченный код") from exc

    async def sign_in_password(self, password: str) -> None:
        try:
            await self._client.sign_in(password=password)
        except errors.PasswordHashInvalidError as exc:
            raise BackendError("Неверный пароль") from exc

    async def load_me(self) -> User:
        me = await self._client.get_me()
        self.me = _user_from_tl(me)
        self._entities[me.id] = me
        self._install_handlers()
        return self.me

    # --- события ----------------------------------------------------------

    def _install_handlers(self) -> None:
        if self._handlers_installed:
            return
        self._handlers_installed = True
        self._client.add_event_handler(self._on_new_message, events.NewMessage())
        self._client.add_event_handler(self._on_edited, events.MessageEdited())
        self._client.add_event_handler(self._on_deleted, events.MessageDeleted())
        self._client.add_event_handler(self._on_reactions, events.Raw(types.UpdateMessageReactions))

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        await event.message.get_sender()
        self._emit(NewMessageEvent(self._convert(event.message)))

    async def _on_edited(self, event: events.MessageEdited.Event) -> None:
        await event.message.get_sender()
        await self._resolve_reaction_peers([event.message])
        self._emit(MessageEditedEvent(self._convert(event.message)))

    async def _on_reactions(self, update: types.UpdateMessageReactions) -> None:
        # Реакции меняются отдельным обновлением, без MessageEdited. Обновляем
        # сообщение, только если оно у нас загружено (иначе его и не видно).
        chat_id = utils.get_peer_id(update.peer)
        raw = self._raw.get((chat_id, update.msg_id))
        if raw is None:
            return
        raw.reactions = _merge_min_reactions(raw.reactions, update.reactions)
        await self._resolve_reaction_peers([raw])
        self._emit(MessageEditedEvent(self._convert(raw)))

    async def _on_deleted(self, event: events.MessageDeleted.Event) -> None:
        self._emit(MessagesDeletedEvent(event.chat_id, list(event.deleted_ids)))

    # --- вспомогательное --------------------------------------------------

    async def _entity(self, peer_id: int):
        if peer_id in self._entities:
            return self._entities[peer_id]
        try:
            entity = await self._client.get_entity(peer_id)
        except ValueError as exc:
            raise BackendError(f"Чат {peer_id} не найден в кэше сессии") from exc
        self._entities[peer_id] = entity
        return entity

    def _remember(self, chat_id: int, msg: TLMessage) -> None:
        key = (chat_id, msg.id)
        self._raw[key] = msg
        self._raw.move_to_end(key)
        while len(self._raw) > _RAW_CACHE_SIZE:
            self._raw.popitem(last=False)

    def _peer_label(self, peer) -> str | None:
        """Подпись того, кто поставил реакцию: «вы», «@username» или имя."""
        peer_id = utils.get_peer_id(peer)
        if self.me and peer_id == self.me.id:
            return "вы"
        entity = self._entities.get(peer_id)
        if entity is None:
            return None
        username = getattr(entity, "username", None)
        return f"@{username}" if username else utils.get_display_name(entity)

    async def _resolve_reaction_peers(self, messages) -> None:
        """Загрузить сущности тех, кто поставил реакции, если их нет в кэше.

        Пользователи из recent_reactions приходят в ответе вместе с сообщениями,
        Telethon кладёт их access_hash в сессию, но сами объекты (с именами) не
        сохраняет — поэтому один пакетный запрос на страницу истории.
        """
        missing: dict[int, object] = {}
        for m in messages:
            for pr in getattr(getattr(m, "reactions", None), "recent_reactions", None) or []:
                peer_id = utils.get_peer_id(pr.peer_id)
                if peer_id not in self._entities and not (self.me and peer_id == self.me.id):
                    missing[peer_id] = pr.peer_id
        if not missing:
            return
        try:
            found = await self._client.get_entity(list(missing.values()))
        except Exception as exc:
            log.debug("Не удалось получить авторов реакций: %s", exc)
            return
        for entity in found:
            self._entities[utils.get_peer_id(entity)] = entity

    def _convert_reactions(self, mr) -> tuple[list[Reaction], bool]:
        if mr is None:
            return [], False
        users: dict[str, list[str]] = {}
        for pr in mr.recent_reactions or []:
            key = _reaction_key(pr.reaction)
            label = self._peer_label(pr.peer_id)
            if key and label and label not in users.setdefault(key, []):
                users[key].append(label)
        result = []
        for rc in mr.results:
            key = _reaction_key(rc.reaction)
            if key is None:
                continue
            result.append(Reaction(
                emoji=key,
                count=rc.count,
                chosen=rc.chosen_order is not None,
                users=users.get(key, [])[: rc.count],
            ))
        return result, bool(mr.can_see_list)

    def _chat_kind(self, entity) -> ChatKind:
        if isinstance(entity, types.User):
            if self.me and entity.id == self.me.id:
                return ChatKind.SAVED
            return ChatKind.BOT if entity.bot else ChatKind.USER
        if isinstance(entity, types.Channel) and entity.broadcast:
            return ChatKind.CHANNEL
        return ChatKind.GROUP

    def _convert_entities(self, text: str, entities) -> list[TextEntity]:
        result = []
        for ent in entities or []:
            kind = _ENTITY_KINDS.get(type(ent))
            if kind is None:
                continue
            offset, length = utf16_span_to_py(text, ent.offset, ent.length)
            result.append(
                TextEntity(
                    kind=kind,
                    offset=offset,
                    length=length,
                    url=getattr(ent, "url", None),
                    user_id=getattr(ent, "user_id", None)
                    if isinstance(getattr(ent, "user_id", None), int)
                    else None,
                )
            )
        return result

    def _describe_media(self, m: TLMessage) -> tuple[MediaKind | None, str]:
        if m.media is None:
            return None, ""
        if m.photo:
            return MediaKind.PHOTO, "фото"
        if m.sticker:
            alt = next(
                (a.alt for a in m.document.attributes if isinstance(a, types.DocumentAttributeSticker)),
                "",
            )
            return MediaKind.STICKER, f"стикер {alt}".strip()
        if m.gif:
            return MediaKind.GIF, "GIF"
        if m.voice:
            return MediaKind.VOICE, f"голосовое {_format_duration(m.file.duration)}".strip()
        if m.video_note:
            return MediaKind.VIDEO, f"видеосообщение {_format_duration(m.file.duration)}".strip()
        if m.video:
            return MediaKind.VIDEO, f"видео {_format_duration(m.file.duration)}".strip()
        if m.audio:
            title = m.file.title or m.file.name or "аудио"
            performer = f"{m.file.performer} — " if m.file.performer else ""
            return MediaKind.AUDIO, f"{performer}{title} {_format_duration(m.file.duration)}".strip()
        if m.document:
            mime = m.file.mime_type or ""
            name = m.file.name or "файл"
            if mime.startswith("image/") and mime != "image/webp":
                return MediaKind.IMAGE, name
            return MediaKind.DOCUMENT, f"{name} ({_format_size(m.file.size)})"
        if m.poll:
            question = m.poll.poll.question
            text = getattr(question, "text", question)
            return MediaKind.POLL, f"опрос: {text}"
        if m.geo:
            return MediaKind.LOCATION, f"геопозиция {m.geo.lat:.5f}, {m.geo.long:.5f}"
        if m.contact:
            c = m.contact
            return MediaKind.CONTACT, f"контакт {c.first_name} {c.last_name} {c.phone_number}".strip()
        if m.web_preview:
            return MediaKind.WEBPAGE, ""
        return MediaKind.OTHER, type(m.media).__name__.removeprefix("MessageMedia")

    def _convert(self, m: TLMessage) -> Message:
        chat_id = m.chat_id
        self._remember(chat_id, m)
        sender = m.sender
        if sender is not None:
            self._entities.setdefault(utils.get_peer_id(sender), sender)
        if m.post and m.chat is not None:
            sender_name = utils.get_display_name(m.chat)
        elif sender is not None:
            sender_name = utils.get_display_name(sender)
        else:
            sender_name = m.post_author or ""
        text = m.message or ""
        media, media_label = self._describe_media(m)
        if m.action is not None and not text:
            text = f"[{type(m.action).__name__.removeprefix('MessageAction')}]"
        reply_to = m.reply_to.reply_to_msg_id if m.reply_to else None
        reactions, listable = self._convert_reactions(m.reactions)
        return Message(
            id=m.id,
            chat_id=chat_id,
            date=m.date or datetime.now(timezone.utc),
            text=text,
            sender_id=m.sender_id,
            sender_name=sender_name,
            outgoing=bool(m.out),
            entities=self._convert_entities(text, m.entities),
            media=media,
            media_label=media_label,
            reply_to_id=reply_to,
            edited=bool(m.edit_date) and not m.edit_hide,
            mentions_me=bool(m.mentioned),
            is_post=bool(m.post),
            grouped_id=m.grouped_id,
            reactions=reactions,
            reactions_listable=listable,
        )

    async def _build_entities(self, text: str, mentions: list[Mention] | None):
        entities = []
        for resolved in resolve_mentions(text, mentions or []):
            offset = py_to_utf16(text, resolved.offset)
            length = py_to_utf16(text, resolved.offset + resolved.length) - offset
            if resolved.mention.needs_entity:
                input_user = await self._client.get_input_entity(resolved.mention.user_id)
                entities.append(types.InputMessageEntityMentionName(offset, length, input_user))
            else:
                entities.append(types.MessageEntityMention(offset, length))
        return entities

    # --- данные -----------------------------------------------------------

    async def get_chats(self, limit: int) -> list[Chat]:
        dialogs = await self._client.get_dialogs(limit=limit)
        chats = []
        for d in dialogs:
            self._entities[d.id] = d.entity
            mute_until = getattr(d.dialog.notify_settings, "mute_until", None)
            last = ""
            if d.message is not None:
                media, label = self._describe_media(d.message)
                last = d.message.message or (f"[{label}]" if label else "")
            chats.append(
                Chat(
                    id=d.id,
                    title="Избранное" if self._chat_kind(d.entity) == ChatKind.SAVED else d.name,
                    kind=self._chat_kind(d.entity),
                    username=getattr(d.entity, "username", None),
                    unread_count=d.unread_count,
                    unread_mentions=d.unread_mentions_count,
                    last_message=last,
                    last_date=d.date,
                    pinned=d.pinned,
                    muted=bool(mute_until and mute_until > datetime.now(timezone.utc)),
                )
            )
        return chats

    async def get_messages(
        self, chat_id: int, limit: int, before_id: int | None = None
    ) -> list[Message]:
        entity = await self._entity(chat_id)
        raw = await self._client.get_messages(entity, limit=limit, offset_id=before_id or 0)
        await self._resolve_reaction_peers(raw)
        return [self._convert(m) for m in reversed(raw)]

    async def send_message(
        self,
        chat_id: int,
        text: str,
        mentions: list[Mention] | None = None,
        reply_to: int | None = None,
    ) -> Message:
        entity = await self._entity(chat_id)
        entities = await self._build_entities(text, mentions)
        msg = await self._client.send_message(
            entity,
            text,
            reply_to=reply_to,
            formatting_entities=entities or None,
            parse_mode=None,
        )
        await msg.get_sender()
        return self._convert(msg)

    async def send_photo(
        self,
        chat_id: int,
        path: Path,
        caption: str = "",
        mentions: list[Mention] | None = None,
        reply_to: int | None = None,
    ) -> Message:
        entity = await self._entity(chat_id)
        entities = await self._build_entities(caption, mentions) if caption else []
        try:
            msg = await self._client.send_file(
                entity,
                str(path),
                # Фото в Telegram — до 10 МБ; больше уйдёт файлом без сжатия.
                force_document=path.stat().st_size > _MAX_PHOTO_UPLOAD,
                caption=caption,
                formatting_entities=entities or None,
                reply_to=reply_to,
                parse_mode=None,
            )
        except errors.RPCError as exc:
            raise BackendError(f"Не удалось отправить фото: {exc}") from exc
        await msg.get_sender()
        result = self._convert(msg)
        if result.has_image:
            # Своя картинка уже есть локально — кладём в кэш под именем, которое
            # ищет download_image, чтобы не качать её обратно с сервера.
            cached = self._config.media_dir / f"{chat_id}_{msg.id}{path.suffix.lower()}"
            try:
                shutil.copyfile(path, cached)
            except OSError:
                log.debug("не удалось положить отправленное фото в кэш", exc_info=True)
        return result

    async def edit_message(
        self, chat_id: int, message_id: int, text: str, mentions: list[Mention] | None = None
    ) -> Message:
        entity = await self._entity(chat_id)
        entities = await self._build_entities(text, mentions)
        try:
            msg = await self._client.edit_message(
                entity, message_id, text, formatting_entities=entities or None, parse_mode=None
            )
        except errors.MessageNotModifiedError:
            raw = self._raw.get((chat_id, message_id))
            if raw is None:
                raise BackendError("Сообщение не изменилось") from None
            msg = raw
        except errors.MessageAuthorRequiredError as exc:
            raise BackendError("Можно редактировать только свои сообщения") from exc
        await msg.get_sender()
        return self._convert(msg)

    async def delete_messages(self, chat_id: int, message_ids: list[int]) -> None:
        entity = await self._entity(chat_id)
        await self._client.delete_messages(entity, message_ids, revoke=True)

    async def mark_read(self, chat_id: int, max_id: int) -> None:
        entity = await self._entity(chat_id)
        await self._client.send_read_acknowledge(entity, max_id=max_id)

    async def search_members(self, chat_id: int, query: str, limit: int = 20) -> list[User]:
        entity = await self._entity(chat_id)
        if isinstance(entity, types.User):
            candidates = [_user_from_tl(entity)]
            return filter_users(candidates, query, limit)
        if isinstance(entity, types.Channel) and entity.broadcast:
            return []  # в каналах упоминать некого

        if chat_id in self._members_complete:
            return filter_users(self._members[chat_id], query, limit)

        try:
            if chat_id not in self._members:
                participants = await self._client.get_participants(
                    entity, limit=_FULL_MEMBERS_LIMIT
                )
                users = [_user_from_tl(u) for u in participants if not u.deleted]
                self._members[chat_id] = users
                if (participants.total or 0) <= _FULL_MEMBERS_LIMIT:
                    self._members_complete.add(chat_id)
                    return filter_users(users, query, limit)
            if not query:
                return self._members[chat_id][:limit]
            found = await self._client.get_participants(entity, search=query, limit=limit)
            return filter_users([_user_from_tl(u) for u in found if not u.deleted], query, limit)
        except errors.ChatAdminRequiredError:
            # Список участников скрыт — предлагаем авторов загруженных сообщений.
            seen: dict[int, User] = {}
            for (cid, _), raw in reversed(self._raw.items()):
                if cid == chat_id and isinstance(raw.sender, types.User):
                    seen.setdefault(raw.sender.id, _user_from_tl(raw.sender))
            return filter_users(list(seen.values()), query, limit)

    # --- медиа и профили --------------------------------------------------

    async def _raw_message(self, message: Message) -> TLMessage | None:
        raw = self._raw.get((message.chat_id, message.id))
        if raw is None:
            entity = await self._entity(message.chat_id)
            raw = await self._client.get_messages(entity, ids=message.id)
            if raw is not None:
                self._remember(message.chat_id, raw)
        return raw

    async def download_image(self, message: Message) -> Path | None:
        if not message.has_image:
            return None
        stem = self._config.media_dir / f"{message.chat_id}_{message.id}"
        cached = next(iter(sorted(stem.parent.glob(stem.name + ".*"))), None)
        if cached is not None:
            return cached
        raw = await self._raw_message(message)
        if raw is None:
            return None
        thumb = None
        if raw.document and (raw.file.size or 0) > _MAX_IMAGE_DOCUMENT:
            thumb = -1  # самое крупное превью вместо оригинала
        path = await self._client.download_media(raw, file=str(stem), thumb=thumb)
        return Path(path) if path else None

    async def download_animation(self, message: Message) -> Path | None:
        if not message.has_animation:
            return None
        anim_dir = self._config.media_dir / "anim"
        anim_dir.mkdir(parents=True, exist_ok=True)
        stem = anim_dir / f"{message.chat_id}_{message.id}"
        cached = next(iter(sorted(anim_dir.glob(stem.name + ".*"))), None)
        if cached is not None:
            return cached
        raw = await self._raw_message(message)
        if raw is None or raw.document is None:
            return None
        if (raw.file.size or 0) > _MAX_ANIMATION:
            raise BackendError(f"Анимация слишком большая ({_format_size(raw.file.size)})")
        ext = _ANIMATION_EXT.get(raw.file.mime_type or "", raw.file.ext or ".bin")
        path = await self._client.download_media(raw, file=str(stem) + ext)
        return Path(path) if path else None

    async def download_avatar(self, peer_id: int, *, big: bool = True) -> Path | None:
        entity = await self._entity(peer_id)
        photo = getattr(entity, "photo", None)
        photo_id = getattr(photo, "photo_id", None)
        if not photo_id:
            return None
        avatars = self._config.media_dir / "avatars"
        avatars.mkdir(parents=True, exist_ok=True)
        stem = avatars / f"{peer_id}_{photo_id}{'' if big else '_s'}"
        cached = next(iter(sorted(avatars.glob(stem.name + ".*"))), None)
        if cached is not None:
            return cached
        path = await self._client.download_profile_photo(entity, file=str(stem), download_big=big)
        return Path(path) if path else None

    async def get_profile(self, peer_id: int) -> Profile:
        entity = await self._entity(peer_id)
        kind = self._chat_kind(entity)
        if isinstance(entity, types.User):
            full = await self._client(functions.users.GetFullUserRequest(entity))
            user = full.users[0] if full.users else entity
            return Profile(
                id=peer_id,
                title=utils.get_display_name(user),
                kind=kind,
                username=user.username,
                phone=f"+{user.phone}" if user.phone else None,
                about=full.full_user.about or "",
                status="бот" if user.bot else _format_status(user.status),
            )
        if isinstance(entity, types.Channel):
            full = await self._client(functions.channels.GetFullChannelRequest(entity))
            count = full.full_chat.participants_count
            noun = "подписчиков" if entity.broadcast else "участников"
            return Profile(
                id=peer_id,
                title=entity.title,
                kind=kind,
                username=entity.username,
                about=full.full_chat.about or "",
                members_count=count,
                status=f"{count} {noun}" if count else "",
            )
        full = await self._client(functions.messages.GetFullChatRequest(entity.id))
        participants = getattr(full.full_chat.participants, "participants", []) or []
        return Profile(
            id=peer_id,
            title=entity.title,
            kind=kind,
            about=full.full_chat.about or "",
            members_count=len(participants) or None,
            status=f"{len(participants)} участников" if participants else "",
        )

    # --- реакции ------------------------------------------------------------

    async def get_available_reactions(self, chat_id: int) -> list[str]:
        if chat_id in self._available_reactions:
            return self._available_reactions[chat_id]
        entity = await self._entity(chat_id)
        standard = list(STANDARD_REACTIONS)
        if isinstance(entity, types.User):
            result = standard
        else:
            try:
                if isinstance(entity, types.Channel):
                    full = await self._client(functions.channels.GetFullChannelRequest(entity))
                else:
                    full = await self._client(functions.messages.GetFullChatRequest(entity.id))
            except errors.RPCError as exc:
                raise BackendError(f"Не удалось узнать доступные реакции: {exc}") from exc
            allowed = full.full_chat.available_reactions
            if isinstance(allowed, types.ChatReactionsNone):
                result = []
            elif isinstance(allowed, types.ChatReactionsSome):
                keys = [_reaction_key(r) for r in allowed.reactions]
                # Только обычные эмодзи: премиум (custom) отсюда не поставить.
                result = [k for k in keys if k and not k.startswith(CUSTOM_PREFIX) and k != PAID]
            else:  # ChatReactionsAll или не задано
                result = standard
        self._available_reactions[chat_id] = result
        return result

    async def send_reaction(self, chat_id: int, message_id: int, emoji: str | None) -> Message:
        entity = await self._entity(chat_id)
        reaction = [] if emoji is None else [types.ReactionEmoji(emoticon=emoji)]
        try:
            result = await self._client(functions.messages.SendReactionRequest(
                peer=entity, msg_id=message_id, reaction=reaction, add_to_recent=True,
            ))
        except errors.RPCError as exc:
            raise BackendError(f"Не удалось поставить реакцию: {exc}") from exc
        raw = self._raw.get((chat_id, message_id))
        update = next(
            (u for u in getattr(result, "updates", []) or []
             if isinstance(u, types.UpdateMessageReactions) and u.msg_id == message_id),
            None,
        )
        if raw is not None and update is not None:
            raw.reactions = _merge_min_reactions(raw.reactions, update.reactions)
        else:
            raw = await self._client.get_messages(entity, ids=message_id)
            if raw is None:
                raise BackendError("Сообщение не найдено")
            await raw.get_sender()
        await self._resolve_reaction_peers([raw])
        return self._convert(raw)

    async def get_reaction_users(self, chat_id: int, message_id: int) -> list[Reaction]:
        entity = await self._entity(chat_id)
        raw = self._raw.get((chat_id, message_id))
        if raw is None or raw.reactions is None:
            return []
        try:
            res = await self._client(functions.messages.GetMessageReactionsListRequest(
                peer=entity, id=message_id, limit=100,
            ))
        except errors.RPCError as exc:
            raise BackendError(f"Не удалось получить список реакций: {exc}") from exc
        for entity_ in [*res.users, *res.chats]:
            self._entities[utils.get_peer_id(entity_)] = entity_
        users: dict[str, list[str]] = {}
        for pr in res.reactions:
            key = _reaction_key(pr.reaction)
            label = self._peer_label(pr.peer_id)
            if key and label and label not in users.setdefault(key, []):
                users[key].append(label)
        reactions, _ = self._convert_reactions(raw.reactions)
        for r in reactions:
            if users.get(r.emoji):
                r.users = users[r.emoji]
        return reactions


def _merge_min_reactions(old, new):
    """В «min»-обновлении реакций нет признака «поставил я» — берём его из старых."""
    if not getattr(new, "min", False) or old is None:
        return new
    chosen = {_reaction_key(r.reaction): r.chosen_order for r in old.results}
    for r in new.results:
        if r.chosen_order is None:
            r.chosen_order = chosen.get(_reaction_key(r.reaction))
    return new
