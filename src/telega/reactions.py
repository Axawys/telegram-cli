"""Реакции на сообщения: значки, названия, стандартный набор, поиск.

В ленте реакция показывается значком («🤡 2: @anna, Олег»), названия нужны
для поиска в окне выбора и меню. Значки берём через display_emoji(): часть
эмодзи по умолчанию «текстовые» и без U+FE0F рисуются узко в одну клетку.

Ключ реакции (Reaction.emoji) — сама эмодзи без селектора вариантов (U+FE0F),
либо «custom:<id>» для премиум-эмодзи, либо «paid» для платной звезды.
"""

from __future__ import annotations

import unicodedata

# Бесплатные реакции Telegram в том порядке, в каком их показывает клиент.
STANDARD_REACTIONS: dict[str, str] = {
    "👍": "like",
    "👎": "dislike",
    "❤": "heart",
    "🔥": "fire",
    "🥰": "love",
    "👏": "clap",
    "😁": "grin",
    "🤔": "thinking",
    "🤯": "mind blown",
    "😱": "scream",
    "🤬": "swear",
    "😢": "cry",
    "🎉": "party",
    "🤩": "star struck",
    "🤮": "vomit",
    "💩": "poop",
    "🙏": "pray",
    "👌": "ok",
    "🕊": "dove",
    "🤡": "clown",
    "🥱": "yawn",
    "🥴": "woozy",
    "😍": "heart eyes",
    "🐳": "whale",
    "❤‍🔥": "heart on fire",
    "🌚": "moon",
    "🌭": "hot dog",
    "💯": "hundred",
    "🤣": "rofl",
    "⚡": "zap",
    "🍌": "banana",
    "🏆": "trophy",
    "💔": "broken heart",
    "🤨": "raised eyebrow",
    "😐": "neutral",
    "🍓": "strawberry",
    "🍾": "champagne",
    "💋": "kiss",
    "🖕": "middle finger",
    "😈": "devil",
    "😴": "sleep",
    "😭": "sob",
    "🤓": "nerd",
    "👻": "ghost",
    "👨‍💻": "coder",
    "👀": "eyes",
    "🎃": "pumpkin",
    "🙈": "see no evil",
    "😇": "angel",
    "😨": "fear",
    "🤝": "handshake",
    "✍": "writing",
    "🤗": "hug",
    "🫡": "salute",
    "🎅": "santa",
    "🎄": "xmas tree",
    "☃": "snowman",
    "💅": "nails",
    "🤪": "crazy",
    "🗿": "moai",
    "🆒": "cool",
    "💘": "cupid",
    "🙉": "hear no evil",
    "🦄": "unicorn",
    "😘": "blow kiss",
    "💊": "pill",
    "🙊": "speak no evil",
    "😎": "sunglasses",
    "👾": "alien monster",
    "🤷‍♂": "shrug man",
    "🤷": "shrug",
    "🤷‍♀": "shrug woman",
    "😡": "angry",
}

CUSTOM_PREFIX = "custom:"
PAID = "paid"


def display_emoji(key: str) -> str:
    """Значок для экрана: «❤» → «❤️» (эмодзи-вид, 2 клетки), премиум — ✨, платная — ⭐."""
    if key.startswith(CUSTOM_PREFIX):
        return "✨"  # премиум-эмодзи — картинка, в терминале её не нарисовать
    if key == PAID:
        return "⭐"
    if key and key[0] in _TEXT_DEFAULT:
        return key[0] + "\ufe0f" + key[1:]
    return key


# Эмодзи из набора, которые без U+FE0F рисуются как текст (узко).
_TEXT_DEFAULT = {"❤", "🕊", "✍", "☃"}


def normalize(emoji: str) -> str:
    """Убрать селекторы вариантов: «❤️» и «❤» — одна реакция."""
    return emoji.replace("\ufe0f", "")


def reaction_name(key: str) -> str:
    """Текстовое название реакции: «🤡» → «clown»."""
    if key.startswith(CUSTOM_PREFIX):
        return "custom emoji"
    if key == PAID:
        return "star"
    key = normalize(key)
    if key in STANDARD_REACTIONS:
        return STANDARD_REACTIONS[key]
    # Неизвестная эмодзи — имя из Unicode без служебных слов.
    names = []
    for ch in key:
        try:
            names.append(unicodedata.name(ch).lower())
        except ValueError:
            continue
    words = [n.removesuffix(" face") for n in names if n not in ("zero width joiner",)]
    return " ".join(words) or key


def filter_reactions(available: list[str], query: str) -> list[str]:
    """Реакции для окна выбора: сначала начинающиеся с запроса, затем содержащие его."""
    q = query.strip().casefold()
    if not q:
        return list(available)
    starts = [r for r in available if reaction_name(r).startswith(q)]
    contains = [r for r in available if r not in starts and q in reaction_name(r)]
    return starts + contains
