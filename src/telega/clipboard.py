"""Чтение системного буфера обмена: картинка или текст (Ctrl+V в поле ввода).

Терминал при Ctrl+V присылает просто клавишу, а не содержимое буфера (вставка
текста у терминалов обычно Ctrl+Shift+V), и картинку через терминал не
передать вовсе. Поэтому буфер читаем сами: Wayland — wl-paste, X11 — xclip.

Что считается картинкой:
  * image/png, image/jpeg, image/webp … в буфере (скриншот, «Копировать
    изображение» в браузере);
  * text/uri-list с путём к файлу-картинке (файл скопирован в файловом
    менеджере).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

log = logging.getLogger(__name__)

# Предпочтение форматов: Telegram принимает их как фото без перекодирования.
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/bmp", "image/gif")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/bmp": ".bmp",
        "image/gif": ".gif"}
_TIMEOUT = 3


@dataclass(frozen=True)
class ClipboardContent:
    image: Path | None = None
    text: str | None = None


class ClipboardError(Exception):
    """Буфер прочитать не удалось — текст для статусной строки."""


async def _run(*cmd: str) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), _TIMEOUT)
    except TimeoutError:
        proc.kill()
        raise ClipboardError("буфер обмена не ответил") from None
    if proc.returncode != 0:
        return b""  # «Nothing is copied» и т. п.
    return out


def _backend() -> tuple[list[str], list[str]]:
    """Команды: (список типов, чтение типа без самого типа)."""
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        return ["wl-paste", "--list-types"], ["wl-paste", "--no-newline", "--type"]
    if os.environ.get("DISPLAY") and shutil.which("xclip"):
        return (["xclip", "-selection", "clipboard", "-o", "-t", "TARGETS"],
                ["xclip", "-selection", "clipboard", "-o", "-t"])
    raise ClipboardError("нет wl-paste (пакет wl-clipboard) или xclip — буфер не прочитать")


def image_file_from_uris(text: str) -> Path | None:
    """Первый файл-картинка из text/uri-list (file:///home/…/a.png)."""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parsed = urlparse(line)
        path = Path(unquote(parsed.path)) if parsed.scheme == "file" else Path(line)
        if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file():
            return path
    return None


async def read_clipboard(dest_dir: Path) -> ClipboardContent:
    """Прочитать буфер. Картинку сохраняет в `dest_dir` и возвращает путь."""
    list_cmd, read_cmd = _backend()
    types = (await _run(*list_cmd)).decode(errors="replace").split()
    for mime in IMAGE_TYPES:
        if mime in types:
            data = await _run(*read_cmd, mime)
            if not data:
                break
            dest_dir.mkdir(parents=True, exist_ok=True)
            path = dest_dir / f"paste-{time.strftime('%Y%m%d-%H%M%S')}{_EXT[mime]}"
            path.write_bytes(data)
            return ClipboardContent(image=path)
    if "text/uri-list" in types:
        uris = (await _run(*read_cmd, "text/uri-list")).decode(errors="replace")
        if (path := image_file_from_uris(uris)) is not None:
            return ClipboardContent(image=path)
    for mime in ("text/plain;charset=utf-8", "UTF8_STRING", "text/plain", "STRING"):
        if mime in types:
            return ClipboardContent(text=(await _run(*read_cmd, mime)).decode(errors="replace"))
    return ClipboardContent()
