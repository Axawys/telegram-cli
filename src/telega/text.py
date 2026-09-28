"""Работа со смещениями в тексте.

Telegram считает смещения сущностей (entities) в UTF-16 code units, а Python —
в кодовых точках. Эмодзи вне BMP (😀) занимают 2 UTF-16 единицы и 1 символ Python,
поэтому без конвертации подсветка «съезжает».
"""

from __future__ import annotations


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def py_to_utf16(text: str, index: int) -> int:
    """Индекс Python-строки → смещение в UTF-16."""
    return utf16_len(text[:index])


def utf16_to_py(text: str, offset: int) -> int:
    """Смещение UTF-16 → индекс Python-строки (с округлением вниз внутри суррогатной пары)."""
    units = 0
    for i, ch in enumerate(text):
        if units >= offset:
            return i
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > offset:
            return i
    return len(text)


def utf16_span_to_py(text: str, offset: int, length: int) -> tuple[int, int]:
    """(offset, length) в UTF-16 → (offset, length) в индексах Python."""
    start = utf16_to_py(text, offset)
    end = utf16_to_py(text, offset + length)
    return start, end - start


def shorten(text: str, width: int) -> str:
    """Однострочное превью: переводы строк → пробелы, обрезка с «…»."""
    line = " ".join(text.split())
    if len(line) <= width:
        return line
    return line[: max(0, width - 1)] + "…"
