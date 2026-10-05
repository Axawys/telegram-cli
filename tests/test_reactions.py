from rich.cells import cell_len

from telega.reactions import (
    STANDARD_REACTIONS,
    display_emoji,
    filter_reactions,
    normalize,
    reaction_name,
)


def test_names():
    assert reaction_name("🤡") == "clown"
    assert reaction_name("❤\ufe0f") == "heart"  # с селектором варианта
    assert reaction_name("❤‍🔥") == "heart on fire"
    assert reaction_name("custom:123") == "custom emoji"
    assert reaction_name("paid") == "star"
    assert reaction_name("🦀") == "crab"  # не из набора Telegram — имя из Unicode


def test_normalize():
    assert normalize("❤\ufe0f") == "❤"
    assert all("\ufe0f" not in key for key in STANDARD_REACTIONS)


def test_filter_prefers_prefix():
    available = list(STANDARD_REACTIONS)
    assert filter_reactions(available, "clo")[0] == "🤡"
    found = filter_reactions(available, "heart")
    assert found[0] == "❤" and "😍" in found  # «heart eyes» тоже, но позже
    assert filter_reactions(available, "  ") == available
    assert filter_reactions(available, "zzz") == []


def test_telethon_reactions_conversion():
    """Разбор настоящих TL-объектов Telethon без сети."""
    from telethon import types

    from telega.backend.telethon_backend import TelethonBackend, _merge_min_reactions
    from telega.models import User

    backend = TelethonBackend.__new__(TelethonBackend)  # без клиента и сети
    backend.me = User(id=1, first_name="Я")
    backend._entities = {
        2: types.User(id=2, first_name="Анна", last_name="Смирнова"),
        3: types.User(id=3, first_name="Олег", username="oleg_p"),
    }
    like, clown = types.ReactionEmoji("👍"), types.ReactionEmoji("🤡")
    mr = types.MessageReactions(
        results=[
            types.ReactionCount(like, 5, chosen_order=0),
            types.ReactionCount(clown, 1),
            types.ReactionCount(types.ReactionCustomEmoji(42), 2),
        ],
        can_see_list=True,
        recent_reactions=[
            types.MessagePeerReaction(types.PeerUser(1), None, like, my=True),
            types.MessagePeerReaction(types.PeerUser(3), None, like),
            types.MessagePeerReaction(types.PeerUser(2), None, clown),
            types.MessagePeerReaction(types.PeerUser(99), None, like),  # неизвестен — пропуск
        ],
    )
    reactions, listable = backend._convert_reactions(mr)
    assert listable
    assert [(r.emoji, r.count, r.chosen, r.users) for r in reactions] == [
        ("👍", 5, True, ["вы", "@oleg_p"]),
        ("🤡", 1, False, ["Анна Смирнова"]),
        ("custom:42", 2, False, []),
    ]

    # «min»-обновление не знает, что реакция моя, — признак берётся из старых.
    update = types.MessageReactions(results=[types.ReactionCount(like, 6)], min=True)
    merged = _merge_min_reactions(mr, update)
    assert merged.results[0].chosen_order == 0


def test_display_emoji_is_two_cells_wide():
    # Текстовые по умолчанию эмодзи получают U+FE0F — иначе узкий значок
    # и съехавшая строка реакций.
    assert display_emoji("❤") == "❤\ufe0f"
    assert display_emoji("🤡") == "🤡"
    assert display_emoji("custom:5") == "✨" and display_emoji("paid") == "⭐"
    assert all(cell_len(display_emoji(e)) == 2 for e in STANDARD_REACTIONS)
