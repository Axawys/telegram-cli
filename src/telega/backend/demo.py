"""Демо-бэкенд: фейковые чаты и сообщения без сети и аккаунта.

Нужен для:
  * разработки UI (`telega --demo`);
  * автотестов интерфейса (tests/test_ui.py).

Картинки и аватарки генерируются Pillow в кэш-каталоге при первом запросе.
Бот «Echo Bot» отвечает на сообщения — так проверяется путь входящих событий.
"""

from __future__ import annotations

import asyncio
import itertools
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from telega.backend import demo_media
from telega.backend.base import Backend, MessageEditedEvent, MessagesDeletedEvent, NewMessageEvent
from telega.mentions import Mention, filter_users, resolve_mentions
from telega.models import (
    BackendError,
    Chat,
    ChatKind,
    EntityKind,
    MediaKind,
    Message,
    Profile,
    Reaction,
    TextEntity,
    User,
)
from telega.reactions import STANDARD_REACTIONS

ME = User(id=1, first_name="Вы", username="me")
PAVEL = User(id=100, first_name="Павел", last_name="Дуров", username="durov")
ANNA = User(id=101, first_name="Анна", last_name="Смирнова")  # без username
OLEG = User(id=102, first_name="Олег", last_name="Петров", username="oleg_p")
MARIA = User(id=103, first_name="Мария", username="masha")
BOT = User(id=200, first_name="Echo Bot", username="echo_bot", is_bot=True)

GROUP_ID = -1001
CHANNEL_ID = -1002
ANIM_ID = -1003

_COLORS = [(94, 129, 172), (163, 190, 140), (208, 135, 112), (180, 142, 173), (235, 203, 139)]


def _entity(text: str, fragment: str, kind: EntityKind, **kw) -> TextEntity:
    return TextEntity(kind=kind, offset=text.index(fragment), length=len(fragment), **kw)


def _label(user: User) -> str:
    """Как бэкенд подписывает автора реакции: «@username» или имя."""
    return f"@{user.username}" if user.username else user.display_name


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """Шрифт с кириллицей (через fontconfig); встроенный шрифт Pillow её не умеет."""
    try:
        path = subprocess.run(
            ["fc-match", "-f", "%{file}", "sans:bold:lang=ru"],
            capture_output=True, text=True, timeout=2, check=True,
        ).stdout
        return ImageFont.truetype(path, size)
    except (OSError, subprocess.SubprocessError):
        return ImageFont.load_default(size)


class DemoBackend(Backend):
    def __init__(self, media_dir: Path, *, echo_delay: float = 1.0) -> None:
        super().__init__()
        self._media_dir = media_dir
        self._echo_delay = echo_delay
        self._ids = itertools.count(1000)
        self._authorized = True
        self._users = {u.id: u for u in (ME, PAVEL, ANNA, OLEG, MARIA, BOT)}
        # Реакции: (чат, сообщение) → {эмодзи: (счётчик, кто поставил)}.
        # В Message.reactions попадают лишь первые двое, как и в Telegram, —
        # остальных отдаёт get_reaction_users().
        self._reactors: dict[tuple[int, int], dict[str, tuple[int, list[str]]]] = {}
        # Отправленные картинки: id сообщения → исходный файл.
        self._uploaded: dict[int, Path] = {}
        # Без фото — в списке чатов будут инициалы.
        self._no_avatar = {BOT.id, ANNA.id}
        self._chats: dict[int, Chat] = {}
        self._messages: dict[int, list[Message]] = {}
        self._members: dict[int, list[User]] = {}
        # id сообщения → (генератор файла, имя файла) для download_animation
        self._anim_files: dict[int, tuple] = {}
        self._build()

    # --- наполнение -------------------------------------------------------

    def _msg(self, chat_id: int, sender: User | None, text: str, minutes_ago: int, **kw) -> Message:
        name = sender.display_name if sender else self._chats[chat_id].title
        return Message(
            id=next(self._ids),
            chat_id=chat_id,
            date=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
            text=text,
            sender_id=sender.id if sender else chat_id,
            sender_name=name,
            outgoing=sender is ME,
            **kw,
        )

    def _build(self) -> None:
        def add_chat(chat: Chat, members: list[User]) -> None:
            self._chats[chat.id] = chat
            self._messages[chat.id] = []
            self._members[chat.id] = members

        add_chat(Chat(ME.id, "Избранное", ChatKind.SAVED, pinned=True), [ME])
        add_chat(Chat(PAVEL.id, PAVEL.display_name, ChatKind.USER, username="durov"), [PAVEL])
        add_chat(
            Chat(GROUP_ID, "Команда telega-cli", ChatKind.GROUP, unread_count=3, unread_mentions=1),
            [ME, PAVEL, ANNA, OLEG, MARIA],
        )
        add_chat(Chat(CHANNEL_ID, "Фото природы", ChatKind.CHANNEL, username="nature", unread_count=2), [])
        add_chat(Chat(BOT.id, BOT.display_name, ChatKind.BOT, username="echo_bot"), [BOT])

        saved = self._messages[ME.id]
        saved.append(self._msg(ME.id, ME, "Заметка: купить молоко", 600))

        dm = self._messages[PAVEL.id]
        dm.append(self._msg(PAVEL.id, PAVEL, "Привет! Как продвигается клиент?", 120))
        dm.append(self._msg(PAVEL.id, ME, "Основа готова, дописываю документацию", 118))
        t = "Отлично. Посмотри https://core.telegram.org/api — там всё про MTProto"
        dm.append(
            self._msg(PAVEL.id, PAVEL, t, 110,
                      entities=[_entity(t, "https://core.telegram.org/api", EntityKind.URL)])
        )

        grp = self._messages[GROUP_ID]
        for i in range(30):
            author = [PAVEL, OLEG, MARIA][i % 3]
            grp.append(self._msg(GROUP_ID, author, f"Сообщение истории №{i + 1}", 300 - i))
        t = "Всем привет! Обсуждаем #roadmap на эту неделю"
        grp.append(self._msg(GROUP_ID, OLEG, t, 30,
                             entities=[_entity(t, "#roadmap", EntityKind.HASHTAG)]))
        t = "@me глянь, пожалуйста, скриншот нового интерфейса"
        grp.append(
            self._msg(GROUP_ID, MARIA, t, 20, mentions_me=True,
                      entities=[_entity(t, "@me", EntityKind.MENTION)])
        )
        grp.append(self._msg(GROUP_ID, MARIA, "", 19, media=MediaKind.PHOTO, media_label="фото"))
        t = "Анна, **жирный** текст и `код` тоже должны подсвечиваться"
        grp.append(
            self._msg(GROUP_ID, OLEG, t, 10, entities=[
                _entity(t, "Анна", EntityKind.MENTION_NAME, user_id=ANNA.id),
                _entity(t, "жирный", EntityKind.BOLD),
                _entity(t, "код", EntityKind.CODE),
            ])
        )
        # Цепочка ответов: Павел → №3 → №1. Space o / gr подгрузит историю,
        # C-o / Space b вернётся назад по цепочке, Space f — снова вперёд.
        grp[2].reply_to_id = grp[0].id
        grp.append(self._msg(GROUP_ID, PAVEL, "Возвращаясь к этому: готово", 5, reply_to_id=grp[2].id))
        roadmap = next(m for m in grp if "#roadmap" in m.text)
        self._set_reactions(roadmap, {
            "👍": [_label(PAVEL), _label(MARIA), _label(ANNA), "вы"],
            "🤡": [_label(ANNA)],
        })
        self._set_reactions(next(m for m in grp if m.mentions_me), {"🔥": [_label(OLEG)]})

        ch = self._messages[CHANNEL_ID]
        ch.append(self._msg(CHANNEL_ID, None, "Закат в горах", 90, media=MediaKind.PHOTO,
                            media_label="фото", is_post=True))
        ch.append(self._msg(CHANNEL_ID, None, "Утро на озере #природа", 45, media=MediaKind.PHOTO,
                            media_label="фото", is_post=True))
        ch.append(self._msg(CHANNEL_ID, None, "Видео с дрона", 5, media=MediaKind.VIDEO,
                            media_label="видео 1:24", is_post=True))
        # В каналах Telegram не показывает, кто поставил, — только счётчики.
        self._set_reactions(ch[0], {"🔥": (154, []), "❤": (37, [])})

        self._messages[BOT.id].append(self._msg(BOT.id, BOT, "Напишите что-нибудь — я повторю.", 60))

        add_chat(Chat(ANIM_ID, "Стикеры и GIF", ChatKind.GROUP, unread_count=4), [ME, OLEG, MARIA])
        anim = self._messages[ANIM_ID]
        anim.append(self._msg(ANIM_ID, OLEG, "Проверка анимаций: j/k — выделение, o — на весь экран", 40))
        samples = [
            (OLEG, MediaKind.GIF, "GIF", demo_media.make_gif_mp4, "gif.mp4"),
            (MARIA, MediaKind.STICKER, "стикер 🎉 (анимированный, .tgs)", demo_media.make_tgs_sticker,
             "sticker.tgs"),
            (OLEG, MediaKind.STICKER, "стикер 🍩 (видео, .webm)", demo_media.make_webm_sticker,
             "sticker.webm"),
            (MARIA, MediaKind.STICKER, "стикер ⭐ (статичный, .webp)", demo_media.make_webp_sticker,
             "sticker.webp"),
        ]
        for n, (who, kind, label, gen, name) in enumerate(samples):
            msg = self._msg(ANIM_ID, who, "", 30 - n, media=kind, media_label=label)
            anim.append(msg)
            self._anim_files[msg.id] = (gen, name)

        for chat_id, msgs in self._messages.items():
            if msgs:
                self._chats[chat_id].last_message = msgs[-1].text or f"[{msgs[-1].media_label}]"
                self._chats[chat_id].last_date = msgs[-1].date

    # --- жизненный цикл ---------------------------------------------------

    async def connect(self) -> None:
        self._media_dir.mkdir(parents=True, exist_ok=True)

    async def disconnect(self) -> None:
        pass

    async def is_authorized(self) -> bool:
        return self._authorized

    async def send_code(self, phone: str) -> None:
        pass

    async def sign_in_code(self, code: str) -> None:
        pass

    async def sign_in_password(self, password: str) -> None:
        pass

    async def load_me(self) -> User:
        self.me = ME
        return ME

    # --- данные -----------------------------------------------------------

    async def get_chats(self, limit: int) -> list[Chat]:
        chats = sorted(
            self._chats.values(),
            key=lambda c: (not c.pinned, -(c.last_date.timestamp() if c.last_date else 0)),
        )
        return chats[:limit]

    async def get_messages(self, chat_id: int, limit: int, before_id: int | None = None) -> list[Message]:
        msgs = self._messages.get(chat_id, [])
        if before_id is not None:
            msgs = [m for m in msgs if m.id < before_id]
        return list(msgs[-limit:])

    def _entities_for(self, text: str, mentions: list[Mention] | None) -> list[TextEntity]:
        return [
            TextEntity(
                kind=EntityKind.MENTION if r.mention.by_username else EntityKind.MENTION_NAME,
                offset=r.offset,
                length=r.length,
                user_id=None if r.mention.by_username else r.mention.user_id,
            )
            for r in resolve_mentions(text, mentions or [])
        ]

    async def send_message(self, chat_id: int, text: str, mentions: list[Mention] | None = None,
                           reply_to: int | None = None) -> Message:
        chat = self._chats[chat_id]
        if chat.kind == ChatKind.CHANNEL:
            raise BackendError("Писать в канал может только администратор")
        msg = self._msg(chat_id, ME, text, 0, reply_to_id=reply_to,
                        entities=self._entities_for(text, mentions))
        self._messages[chat_id].append(msg)
        chat.last_message, chat.last_date = text, msg.date
        if chat.kind == ChatKind.BOT:
            asyncio.get_running_loop().call_later(self._echo_delay, self._echo, chat_id, text)
        return msg

    async def send_photo(self, chat_id: int, path: Path, caption: str = "",
                         mentions: list[Mention] | None = None, reply_to: int | None = None) -> Message:
        chat = self._chats[chat_id]
        if chat.kind == ChatKind.CHANNEL:
            raise BackendError("Писать в канал может только администратор")
        await asyncio.sleep(0.05)  # имитация загрузки
        msg = self._msg(chat_id, ME, caption, 0, reply_to_id=reply_to, media=MediaKind.PHOTO,
                        media_label="фото", entities=self._entities_for(caption, mentions))
        self._uploaded[msg.id] = Path(path)
        self._messages[chat_id].append(msg)
        chat.last_message, chat.last_date = caption or "[фото]", msg.date
        return msg

    def _echo(self, chat_id: int, text: str) -> None:
        reply = self._msg(chat_id, BOT, f"Эхо: {text}", 0)
        self._messages[chat_id].append(reply)
        self._emit(NewMessageEvent(reply))

    async def edit_message(self, chat_id: int, message_id: int, text: str,
                           mentions: list[Mention] | None = None) -> Message:
        for msg in self._messages[chat_id]:
            if msg.id == message_id:
                if not msg.outgoing:
                    raise BackendError("Можно редактировать только свои сообщения")
                msg.text, msg.edited = text, True
                msg.entities = self._entities_for(text, mentions)
                self._emit(MessageEditedEvent(msg))
                return msg
        raise BackendError("Сообщение не найдено")

    # --- реакции ------------------------------------------------------------

    def _set_reactions(self, msg: Message, reactors: dict) -> None:
        table = {
            emoji: value if isinstance(value, tuple) else (len(value), list(value))
            for emoji, value in reactors.items()
        }
        self._reactors[(msg.chat_id, msg.id)] = table
        msg.reactions_listable = self._chats[msg.chat_id].kind != ChatKind.CHANNEL
        msg.reactions = [
            Reaction(emoji, count, chosen="вы" in users, users=users[:2])
            for emoji, (count, users) in table.items() if count
        ]

    def _find(self, chat_id: int, message_id: int) -> Message:
        msg = next((m for m in self._messages.get(chat_id, []) if m.id == message_id), None)
        if msg is None:
            raise BackendError("Сообщение не найдено")
        return msg

    async def get_available_reactions(self, chat_id: int) -> list[str]:
        if self._chats[chat_id].kind == ChatKind.CHANNEL:
            return ["👍", "❤", "🔥", "🎉"]  # канал ограничил набор
        return list(STANDARD_REACTIONS)

    async def send_reaction(self, chat_id: int, message_id: int, emoji: str | None) -> Message:
        msg = self._find(chat_id, message_id)
        if emoji is not None and emoji not in await self.get_available_reactions(chat_id):
            raise BackendError("Эта реакция в чате запрещена")
        table = {}
        for key, (count, users) in self._reactors.get((chat_id, message_id), {}).items():
            if "вы" in users:
                count, users = count - 1, [u for u in users if u != "вы"]
            table[key] = (count, users)
        if emoji is not None:
            count, users = table.get(emoji, (0, []))
            table[emoji] = (count + 1, ["вы", *users])
        self._set_reactions(msg, table)
        self._emit(MessageEditedEvent(msg))
        return msg

    async def get_reaction_users(self, chat_id: int, message_id: int) -> list[Reaction]:
        self._find(chat_id, message_id)
        return [
            Reaction(emoji, count, chosen="вы" in users, users=list(users))
            for emoji, (count, users) in self._reactors.get((chat_id, message_id), {}).items() if count
        ]

    async def delete_messages(self, chat_id: int, message_ids: list[int]) -> None:
        ids = set(message_ids)
        self._messages[chat_id] = [m for m in self._messages[chat_id] if m.id not in ids]
        self._emit(MessagesDeletedEvent(chat_id, message_ids))

    async def mark_read(self, chat_id: int, max_id: int) -> None:
        self._chats[chat_id].unread_count = 0
        self._chats[chat_id].unread_mentions = 0

    async def search_members(self, chat_id: int, query: str, limit: int = 20) -> list[User]:
        members = [u for u in self._members.get(chat_id, []) if u is not ME]
        return filter_users(members, query, limit)

    # --- медиа и профили --------------------------------------------------

    def _generate(self, path: Path, size: tuple[int, int], seed: int, avatar: str | None = None) -> Path:
        if path.exists():
            return path
        w, h = size
        c1 = _COLORS[seed % len(_COLORS)]
        c2 = _COLORS[(seed + 2) % len(_COLORS)]
        img = Image.new("RGB", size)
        draw = ImageDraw.Draw(img)
        for y in range(h):
            t = y / max(1, h - 1)
            color = tuple(int(a + (b - a) * t) for a, b in zip(c1, c2, strict=True))
            draw.line([(0, y), (w, y)], fill=color)
        if avatar:
            draw.ellipse([w * 0.1, h * 0.1, w * 0.9, h * 0.9], outline=(255, 255, 255), width=6)
            draw.text((w / 2, h / 2), avatar, fill=(255, 255, 255), anchor="mm", font=_font(h // 3))
        else:
            # «горы» и «солнце», чтобы картинка была похожа на фото
            draw.ellipse([w * 0.65, h * 0.15, w * 0.8, h * 0.15 + w * 0.15], fill=(250, 230, 160))
            draw.polygon([(0, h), (w * 0.3, h * 0.45), (w * 0.55, h), ], fill=(46, 52, 64))
            draw.polygon([(w * 0.35, h), (w * 0.7, h * 0.35), (w, h * 0.8), (w, h)], fill=(59, 66, 82))
        img.save(path)
        return path

    async def download_image(self, message: Message) -> Path | None:
        if not message.has_image:
            return None
        if message.id in self._uploaded:
            return self._uploaded[message.id]
        await asyncio.sleep(0.05)  # имитация сети
        path = self._media_dir / f"demo_{message.chat_id}_{message.id}.png"
        return self._generate(path, (640, 400), message.id)

    async def download_animation(self, message: Message) -> Path | None:
        entry = self._anim_files.get(message.id)
        if entry is None:
            return None
        gen, name = entry
        path = self._media_dir / f"demo_{name}"
        if not path.exists():
            # генерация через PyAV/libvpx — CPU, уводим из event loop
            await asyncio.to_thread(gen, path)
        return path

    async def download_avatar(self, peer_id: int, *, big: bool = True) -> Path | None:
        if peer_id in self._no_avatar:
            return None
        title = self._users[peer_id].display_name if peer_id in self._users else self._chats[peer_id].title
        size = 320 if big else 64
        path = self._media_dir / f"demo_avatar_{peer_id}_{size}.png"
        return self._generate(path, (size, size), abs(peer_id), avatar=title[:1].upper())

    async def get_profile(self, peer_id: int) -> Profile:
        if peer_id in self._users:
            u = self._users[peer_id]
            return Profile(
                id=u.id,
                title=u.display_name,
                kind=ChatKind.BOT if u.is_bot else ChatKind.USER,
                username=u.username,
                phone=None if u.is_bot else "+7 900 000-00-00",
                about="Демо-пользователь telega-cli",
                status="бот" if u.is_bot else "в сети",
            )
        chat = self._chats.get(peer_id)
        if chat is None:
            raise BackendError("Профиль не найден")
        members = len(self._members.get(peer_id, [])) or 1280
        return Profile(
            id=chat.id,
            title=chat.title,
            kind=chat.kind,
            username=chat.username,
            about="Демо-чат для разработки интерфейса",
            members_count=members,
            status=f"{members} {'подписчиков' if chat.kind == ChatKind.CHANNEL else 'участников'}",
        )
