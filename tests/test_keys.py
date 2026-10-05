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
    actions = {a.partition(":")[0] for keys in DEFAULT_KEYMAP.values() for a in keys.values()}
    assert actions <= set(ACTION_HELP), actions - set(ACTION_HELP)


def test_action_with_argument():
    from telega.reactions import STANDARD_REACTIONS
    from telega.vim.keymap import action_help

    p = KeyParser(DEFAULT_KEYMAP)
    action = feed_all(p, "<Space>lc")
    assert (action.name, action.arg) == ("react", "🤡")
    assert action_help("react:🤡") == "🤡  clown"
    assert action_help("react:❤") == "❤\ufe0f  heart"
    # Все реакции из меню — из стандартного набора Telegram.
    menu = [a.partition(":")[2] for a in DEFAULT_KEYMAP["global"].values() if a.startswith("react:")]
    assert menu and all(e in STANDARD_REACTIONS for e in menu)


def test_leader_continuations():
    p = KeyParser(DEFAULT_KEYMAP)
    assert p.continuations("chats") == []
    assert feed_all(p, "<Space>", "chats") is None
    assert p.prefix == ("space",)
    found = dict(p.continuations("chats"))
    assert found["e"] == "toggle_chat_list"
    assert found["space"] == "find_chat"
    assert found["q"] is None  # группа: <Space>qq
    assert p.feed("q", "chats") is None
    assert p.continuations("chats") == [("q", "quit")]
    p.back()
    assert p.prefix == ("space",)
    assert p.feed("e", "chats").name == "toggle_chat_list"
    assert p.prefix == ()


def test_continuations_context_and_pending_display():
    p = KeyParser(DEFAULT_KEYMAP)
    feed_all(p, "3g", "messages")
    assert p.pending == "3g"
    found = dict(p.continuations("messages"))
    assert found["g"] == "cursor_first" and found["r"] == "goto_reply"
    assert "r" not in dict(p.continuations("chats"))
    p.reset()
    feed_all(p, "<Space>", "chats")
    assert p.pending == "SPC"


def test_chat_initials():
    from telega.ui.widgets.avatar import initials

    assert initials("Павел Дуров") == "ПД"
    assert initials("telega-cli") == "T"
    assert initials("Команда telega cli") == "КT"
    assert initials("🔥 Новости") == "Н"
    assert initials("") == "?"
