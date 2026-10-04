"""Разбор vim-подобных последовательностей клавиш.

Не зависит от Textual: на вход подаются токены клавиш («j», «G», «ctrl+d»,
«enter»), на выходе — имя действия и счётчик. Это позволяет покрыть логику
тестами и в будущем читать раскладку из конфига.

Нотация последовательностей как в vim: «gg», «dd», «<C-d>», «<CR>», «<Esc>».
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Mode(StrEnum):
    NORMAL = "NORMAL"
    INSERT = "INSERT"
    COMMAND = "COMMAND"  # строка «:»
    SEARCH = "SEARCH"  # строка «/»


# Имена специальных клавиш vim → имена клавиш Textual.
_SPECIAL = {
    "cr": "enter",
    "enter": "enter",
    "return": "enter",
    "esc": "escape",
    "tab": "tab",
    "s-tab": "shift+tab",
    "space": "space",
    "bs": "backspace",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "home": "home",
    "end": "end",
    "pageup": "pageup",
    "pagedown": "pagedown",
    "del": "delete",
}

_TOKEN_RE = re.compile(r"<[^<>]+>|.")


def parse_sequence(spec: str) -> tuple[str, ...]:
    """«g<C-d>» → ("g", "ctrl+d")."""
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(spec):
        if len(raw) > 2 and raw.startswith("<") and raw.endswith(">"):
            name = raw[1:-1].lower()
            if name.startswith(("c-", "a-", "m-")):
                mod = {"c": "ctrl", "a": "alt", "m": "alt"}[name[0]]
                key = name[2:]
                tokens.append(f"{mod}+{_SPECIAL.get(key, key)}")
            elif name in _SPECIAL:
                tokens.append(_SPECIAL[name])
            else:
                raise ValueError(f"Неизвестная клавиша {raw!r} в {spec!r}")
        else:
            tokens.append("space" if raw == " " else raw)
    return tuple(tokens)


@dataclass(frozen=True, slots=True)
class Action:
    name: str
    count: int = 1
    has_count: bool = False


class KeyParser:
    """Накопитель клавиш: счётчик + многоклавишные последовательности.

    keymaps: {контекст: {последовательность: действие}}. При поиске сначала
    проверяется текущий контекст, затем «global».
    """

    GLOBAL = "global"

    def __init__(self, keymaps: dict[str, dict[str, str]]):
        self._maps: dict[str, dict[tuple[str, ...], str]] = {
            ctx: {parse_sequence(seq): action for seq, action in keys.items()}
            for ctx, keys in keymaps.items()
        }
        self._count = ""
        self._pending: list[str] = []

    @property
    def pending(self) -> str:
        """Набранное, но ещё не завершённое — для отображения в статусной строке."""
        return self._count + "".join(display_token(t) for t in self._pending)

    @property
    def prefix(self) -> tuple[str, ...]:
        """Начатая многоклавишная последовательность (без счётчика)."""
        return tuple(self._pending)

    def back(self) -> None:
        """Убрать последнюю клавишу последовательности (Backspace в WhichKey)."""
        if self._pending:
            self._pending.pop()
        if not self._pending:
            self._count = ""

    def continuations(self, context: str) -> list[tuple[str, str | None]]:
        """Возможные следующие клавиши для начатой последовательности.

        Возвращает [(клавиша, действие)], где действие None означает группу —
        после клавиши последовательность ещё не закончится. Порядок — как в
        раскладке, контекст панели перекрывает «global».
        """
        prefix = tuple(self._pending)
        if not prefix:
            return []
        n = len(prefix)
        found: dict[str, str | None] = {}
        for keymap in self._candidates(context):
            for seq, action in keymap.items():
                if len(seq) <= n or seq[:n] != prefix:
                    continue
                key = seq[n]
                if len(seq) > n + 1:
                    found.setdefault(key, None)
                elif found.get(key) is None:
                    # точное совпадение срабатывает раньше более длинных
                    found[key] = action
        return list(found.items())

    def reset(self) -> None:
        self._count = ""
        self._pending.clear()

    def _candidates(self, context: str) -> list[dict[tuple[str, ...], str]]:
        maps = [self._maps.get(context, {})]
        if context != self.GLOBAL:
            maps.append(self._maps.get(self.GLOBAL, {}))
        return maps

    def feed(self, token: str, context: str) -> Action | None:
        """Подать клавишу. Возвращает действие, если последовательность завершена.

        None означает «ждём продолжения» или «такой последовательности нет»
        (во втором случае буфер сбрасывается).
        """
        if not self._pending and token.isdigit() and (token != "0" or self._count):
            self._count += token
            return None

        self._pending.append(token)
        seq = tuple(self._pending)
        maps = self._candidates(context)

        for keymap in maps:
            if seq in keymap:
                action = Action(
                    name=keymap[seq],
                    count=int(self._count) if self._count else 1,
                    has_count=bool(self._count),
                )
                self.reset()
                return action

        if any(k[: len(seq)] == seq for keymap in maps for k in keymap):
            return None  # префикс более длинной последовательности

        self.reset()
        return None


def display_token(token: str) -> str:
    """Токен → как показывать пользователю: «space» → «SPC», «ctrl+d» → «<C-d>»."""
    if token == "space":
        return "SPC"
    if len(token) == 1:
        return token
    if token.startswith("ctrl+"):
        return f"<C-{token[5:]}>"
    return f"<{token.capitalize()}>"


def token_from_event(key: str, character: str | None) -> str:
    """Превратить клавишу Textual в токен парсера.

    Для печатных символов берём сам символ («G», «:», «?»), чтобы не зависеть
    от того, как Textual называет shift-комбинации.
    """
    if character == " ":
        return "space"
    if character and len(character) == 1 and character.isprintable() and "+" not in key:
        return character
    return key
