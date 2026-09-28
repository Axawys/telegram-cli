from datetime import datetime, timezone

from telega.models import EntityKind, Message, TextEntity
from telega.text import py_to_utf16, shorten, utf16_len, utf16_span_to_py, utf16_to_py
from telega.ui.render import message_body


def test_utf16_len_emoji():
    assert utf16_len("a😀b") == 4


def test_roundtrip_with_emoji():
    text = "😀 привет @durov"
    idx = text.index("@durov")
    off = py_to_utf16(text, idx)
    assert off == idx + 1  # эмодзи занимает 2 единицы UTF-16
    assert utf16_to_py(text, off) == idx
    assert utf16_span_to_py(text, off, 6) == (idx, 6)


def test_shorten():
    assert shorten("a\nb  c", 10) == "a b c"
    assert shorten("abcdef", 4) == "abc…"


def test_message_body_highlights_mention():
    text = "hi @durov"
    msg = Message(
        id=1, chat_id=1, date=datetime.now(timezone.utc), text=text,
        entities=[TextEntity(EntityKind.MENTION, 3, 6)],
    )
    rendered = message_body(msg)
    assert rendered.plain == text
    assert any(span.start == 3 and span.end == 9 for span in rendered.spans)
