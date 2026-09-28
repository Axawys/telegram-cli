import pytest

from telega.vim import DEFAULT_KEYMAP, KeyParser, parse_sequence, token_from_event
from telega.vim.keymap import ACTION_HELP


def feed_all(parser: KeyParser, keys: str, context: str = "messages"):
    result = None
    for token in parse_sequence(keys):
        result = parser.feed(token, context)
    return result


def test_parse_sequence():
    assert parse_sequence("gg") == ("g", "g")
    assert parse_sequence("<C-d>") == ("ctrl+d",)
    assert parse_sequence("g<CR>") == ("g", "enter")
    assert parse_sequence("<Esc>") == ("escape",)


def test_parse_sequence_unknown():
    with pytest.raises(ValueError):
        parse_sequence("<Foo>")


def test_single_key():
    p = KeyParser(DEFAULT_KEYMAP)
    action = feed_all(p, "j")
    assert action.name == "cursor_down" and action.count == 1 and not action.has_count


def test_count():
    p = KeyParser(DEFAULT_KEYMAP)
    action = feed_all(p, "12j")
    assert action.name == "cursor_down" and action.count == 12 and action.has_count


def test_multi_key_and_pending():
    p = KeyParser(DEFAULT_KEYMAP)
    assert p.feed("g", "messages") is None
    assert p.pending == "g"
    assert p.feed("g", "messages").name == "cursor_first"
    assert p.pending == ""


def test_unknown_sequence_resets():
    p = KeyParser(DEFAULT_KEYMAP)
    assert feed_all(p, "gx") is None
    assert p.pending == ""
    assert feed_all(p, "j").name == "cursor_down"


def test_context_falls_back_to_global():
    p = KeyParser(DEFAULT_KEYMAP)
    assert feed_all(p, ":", "chats").name == "command_line"
    assert feed_all(p, "dd", "messages").name == "delete"
    # dd нет в списке чатов
    assert feed_all(p, "dd", "chats") is None


def test_zero_is_not_count_start():
    p = KeyParser({"global": {"0": "line_start"}})
    assert p.feed("0", "global").name == "line_start"


def test_token_from_event():
    assert token_from_event("G", "G") == "G"
    assert token_from_event("colon", ":") == ":"
    assert token_from_event("ctrl+d", "\x04") == "ctrl+d"
    assert token_from_event("enter", "\r") == "enter"
    assert token_from_event("space", " ") == "space"


def test_every_action_has_help():
    actions = {a for keys in DEFAULT_KEYMAP.values() for a in keys.values()}
    assert actions <= set(ACTION_HELP), actions - set(ACTION_HELP)
