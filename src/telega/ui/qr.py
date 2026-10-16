"""QR-код текстом: две строки модулей в одну строку терминала (▀ / ▄ / █).

Цвета — чёрный и белый в hex, а не ANSI-имена: ANSI переводятся палитрой
темы (telega/ui/themes.py), и в некоторых темах контраст стал бы слишком
низким для камеры телефона.
"""

from __future__ import annotations

import segno
from rich.text import Text

_DARK, _LIGHT = "#000000", "#ffffff"


def qr_text(data: str, border: int = 2) -> Text:
    matrix = [list(row) for row in segno.make(data, error="l").matrix_iter(border=border)]
    if len(matrix) % 2:
        matrix.append([0] * len(matrix[0]))  # чётное число строк для пар
    text = Text(no_wrap=True)
    for top, bottom in zip(matrix[::2], matrix[1::2], strict=True):
        for up, down in zip(top, bottom, strict=True):
            text.append("▀", style=f"{_DARK if up else _LIGHT} on {_DARK if down else _LIGHT}")
        text.append("\n")
    text.rstrip()
    return text
