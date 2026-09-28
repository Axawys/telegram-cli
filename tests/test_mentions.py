from telega.mentions import (
    Mention,
    MentionQuery,
    apply_completion,
    filter_users,
    find_query,
    resolve_mentions,
)
from telega.models import User

ANNA = User(id=1, first_name="Анна", last_name="Смирнова")
DUROV = User(id=2, first_name="Павел", last_name="Дуров", username="durov")


def test_find_query_at_start():
    assert find_query("@du", 3) == MentionQuery(0, 3, "du")


def test_find_query_empty_after_at():
    assert find_query("привет @", 8) == MentionQuery(7, 8, "")


def test_find_query_cyrillic():
    assert find_query("эй @Ан", 6) == MentionQuery(3, 6, "Ан")


def test_find_query_ignores_email():
    assert find_query("mail user@host", 14) is None


def test_find_query_cursor_not_at_word_end():
    # курсор после пробела — упоминание уже закончено
    assert find_query("@durov ", 7) is None


def test_find_query_after_bracket():
    assert find_query("(@du", 4) == MentionQuery(1, 4, "du")


def test_apply_completion_username():
    text, cursor, mention = apply_completion("hi @du", MentionQuery(3, 6, "du"), DUROV)
    assert text == "hi @durov "
    assert cursor == len(text)
    assert mention == Mention("@durov", 2, by_username=True)
    assert not mention.needs_entity


def test_apply_completion_no_username_keeps_tail():
    text, cursor, mention = apply_completion("@Ан как дела", MentionQuery(0, 3, "Ан"), ANNA)
    assert text == "Анна как дела"
    assert cursor == 4
    assert mention.needs_entity


def test_resolve_mentions_after_edit():
    mentions = [Mention("Анна", 1, False), Mention("@durov", 2, True)]
    text = "Смотри, @durov и Анна!"
    resolved = resolve_mentions(text, mentions)
    assert [(r.mention.user_id, r.offset, r.length) for r in resolved] == [(2, 8, 6), (1, 17, 4)]


def test_resolve_mentions_removed_mention_is_skipped():
    assert resolve_mentions("никого", [Mention("Анна", 1, False)]) == []


def test_resolve_mentions_word_boundary():
    # «Анна» внутри «Аннабель» — не упоминание
    assert resolve_mentions("Аннабель", [Mention("Анна", 1, False)]) == []


def test_resolve_mentions_same_label_twice():
    mentions = [Mention("Анна", 1, False), Mention("Анна", 3, False)]
    resolved = resolve_mentions("Анна и Анна", mentions)
    assert [(r.mention.user_id, r.offset) for r in resolved] == [(1, 0), (3, 7)]


def test_filter_users_prefix_first():
    users = [ANNA, DUROV, User(id=3, first_name="Дуня")]
    assert [u.id for u in filter_users(users, "ду")] == [3, 2] or [u.id for u in filter_users(users, "ду")] == [2, 3]
    assert [u.id for u in filter_users(users, "dur")] == [2]
    assert [u.id for u in filter_users(users, "мирн")] == [1]
