"""Логика упоминаний (@теги) без привязки к UI и Telegram-библиотеке.

Три задачи:
1. `find_query` — понять, набирает ли пользователь сейчас упоминание
   (курсор стоит сразу после «@что-то»), и вернуть что именно.
2. `apply_completion` — заменить «@запрос» на выбранного участника.
3. `resolve_mentions` — перед отправкой найти вставленные упоминания в
   итоговом тексте и вернуть их позиции (текст мог быть отредактирован
   после вставки, поэтому позиции не хранятся, а ищутся заново).

Пользователь с username вставляется как «@username» — такой тег Telegram
понимает сам. Пользователь без username вставляется как его имя, и к
сообщению прикладывается сущность MentionName с его id — так делает
официальный клиент.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from telega.models import User

# Символы, которые могут входить в запрос после «@». Username в Telegram —
# латиница, цифры и «_», но ищем и по имени, поэтому пускаем любые буквы.
_QUERY_CHAR = re.compile(r"[\w]", re.UNICODE)


@dataclass(frozen=True, slots=True)
class MentionQuery:
    start: int  # индекс символа «@»
    end: int  # индекс курсора
    query: str  # текст после «@» (может быть пустым)


@dataclass(frozen=True, slots=True)
class Mention:
    """Вставленное в поле ввода упоминание."""

    label: str  # то, что видно в тексте: «@durov» или «Павел»
    user_id: int
    by_username: bool

    @property
    def needs_entity(self) -> bool:
        """Нужна ли явная сущность MentionName (у пользователя нет username)."""
        return not self.by_username


@dataclass(frozen=True, slots=True)
class ResolvedMention:
    mention: Mention
    offset: int  # индекс Python-строки
    length: int


def find_query(text: str, cursor: int) -> MentionQuery | None:
    """Найти упоминание, которое пользователь набирает в позиции `cursor`.

    «@» должен стоять в начале текста или после пробельного символа /
    открывающей скобки, чтобы e-mail вида user@host не открывал подсказки.
    """
    if cursor > len(text):
        return None
    i = cursor
    while i > 0 and _QUERY_CHAR.match(text[i - 1]):
        i -= 1
    if i == 0 or text[i - 1] != "@":
        return None
    at = i - 1
    if at > 0 and not (text[at - 1].isspace() or text[at - 1] in "([{«\"'"):
        return None
    return MentionQuery(start=at, end=cursor, query=text[i:cursor])


def label_for(user: User) -> tuple[str, bool]:
    """Текст, который вставляется в поле ввода, и признак «по username»."""
    if user.username:
        return f"@{user.username}", True
    return user.first_name or user.display_name, False


def apply_completion(text: str, query: MentionQuery, user: User) -> tuple[str, int, Mention]:
    """Подставить пользователя вместо «@запрос».

    Возвращает новый текст, новую позицию курсора и описание упоминания.
    После упоминания добавляется пробел, если его ещё нет.
    """
    label, by_username = label_for(user)
    tail = text[query.end :]
    suffix = "" if tail.startswith((" ", "\n")) else " "
    new_text = text[: query.start] + label + suffix + tail
    cursor = query.start + len(label) + len(suffix)
    return new_text, cursor, Mention(label=label, user_id=user.id, by_username=by_username)


def _is_boundary(text: str, index: int) -> bool:
    """Символ `text[index]` не является частью слова (или индекс вне строки)."""
    return index < 0 or index >= len(text) or not _QUERY_CHAR.match(text[index])


def resolve_mentions(text: str, mentions: list[Mention]) -> list[ResolvedMention]:
    """Найти вставленные упоминания в итоговом тексте.

    Каждое вставленное упоминание сопоставляется с очередным ещё не занятым
    вхождением своей метки (слева направо). Если пользователь стёр упоминание,
    оно просто не найдётся. Результат отсортирован по позиции, пересечений нет.
    """
    taken: list[tuple[int, int]] = []
    result: list[ResolvedMention] = []

    def overlaps(a: int, b: int) -> bool:
        return any(a < e and s < b for s, e in taken)

    for mention in mentions:
        pos = 0
        while (idx := text.find(mention.label, pos)) != -1:
            end = idx + len(mention.label)
            if (
                not overlaps(idx, end)
                and _is_boundary(text, idx - 1)
                and _is_boundary(text, end)
            ):
                taken.append((idx, end))
                result.append(ResolvedMention(mention, idx, len(mention.label)))
                break
            pos = idx + 1
    result.sort(key=lambda r: r.offset)
    return result


def filter_users(users: list[User], query: str, limit: int = 20) -> list[User]:
    """Локальный поиск участников: сначала совпадения с начала username/имени."""
    q = query.casefold()
    if not q:
        return users[:limit]

    def rank(user: User) -> int | None:
        fields = [user.username or "", user.first_name, user.last_name, user.display_name]
        fields = [f.casefold() for f in fields if f]
        if any(f.startswith(q) for f in fields):
            return 0
        if any(q in f for f in fields):
            return 1
        return None

    ranked = [(r, u) for u in users if (r := rank(u)) is not None]
    ranked.sort(key=lambda item: (item[0], item[1].display_name.casefold()))
    return [u for _, u in ranked[:limit]]
