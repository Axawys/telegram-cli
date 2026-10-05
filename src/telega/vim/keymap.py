"""Раскладка по умолчанию для NORMAL-режима.

Контексты:
  global   — действует всегда (если не переопределено в контексте панели)
  chats    — фокус на списке чатов
  messages — фокус на ленте сообщений

Лидер — <Space>, как в LazyVim: после него снизу появляется окно с
доступными продолжениями (WhichKey). Названия групп — в KEY_GROUPS.

Имена действий соответствуют методам `vim_<имя>` в
`telega.ui.screens.main.MainScreen`. Чтобы добавить команду: допишите строку
сюда, реализуйте метод там, добавьте описание в ACTION_HELP и опишите
клавишу в docs/KEYBINDINGS.md.
"""

from __future__ import annotations

DEFAULT_KEYMAP: dict[str, dict[str, str]] = {
    "global": {
        ":": "command_line",
        "/": "search",
        "?": "help",
        "<Tab>": "toggle_pane",
        "<C-h>": "focus_chats",
        "<C-l>": "focus_messages",
        "<C-n>": "toggle_chat_list",
        "<C-v>": "paste",
        "i": "insert",
        "a": "insert",
        "ZZ": "quit",
        "ZQ": "quit",
        "n": "search_next",
        "N": "search_prev",
        "<Esc>": "cancel",
        # Лидер (<Space>), как в LazyVim.
        "<Space><Space>": "find_chat",
        "<Space>e": "toggle_chat_list",
        "<Space>/": "search",
        "<Space>:": "command_line",
        "<Space>?": "help",
        "<Space>t": "theme",
        "<Space>ww": "toggle_pane",
        "<Space>wh": "focus_chats",
        "<Space>wl": "focus_messages",
        "<Space>pc": "chat_profile",
        "<Space>pm": "my_profile",
        "<Space>r": "reply",
        "<Space>o": "goto_reply",
        # Реакции: Space l — группа, следующая клавиша — сама реакция.
        "<Space>l/": "react",
        "<Space>ll": "react:👍",
        "<Space>ld": "react:👎",
        "<Space>lh": "react:❤",
        "<Space>lf": "react:🔥",
        "<Space>lc": "react:🤡",
        "<Space>lp": "react:🎉",
        "<Space>lt": "react:🤔",
        "<Space>lg": "react:😁",
        "<Space>lr": "react:🤣",
        "<Space>ls": "react:😢",
        "<Space>le": "react:👀",
        "<Space>lo": "react:👌",
        "<Space>lw": "react:🤯",
        "<Space>l1": "react:💯",
        "<Space>lx": "unreact",
        "<Space>b": "jump_back",
        "<Space>f": "jump_forward",
        "<Space>Rc": "reload_chats",
        "<Space>Rm": "reload_messages",
        "<Space>qq": "quit",
    },
    "chats": {
        "j": "cursor_down",
        "k": "cursor_up",
        "<Down>": "cursor_down",
        "<Up>": "cursor_up",
        "gg": "cursor_first",
        "G": "cursor_last",
        "<C-d>": "half_page_down",
        "<C-u>": "half_page_up",
        "<C-f>": "page_down",
        "<C-b>": "page_up",
        "l": "open_chat",
        "o": "open_chat",
        "<CR>": "open_chat",
        "<Right>": "open_chat",
        "K": "profile",
        "gp": "profile",
        "R": "reload_chats",
    },
    "messages": {
        "j": "cursor_down",
        "k": "cursor_up",
        "<Down>": "cursor_down",
        "<Up>": "cursor_up",
        "gg": "cursor_first",
        "G": "cursor_last",
        "<C-d>": "half_page_down",
        "<C-u>": "half_page_up",
        "<C-f>": "page_down",
        "<C-b>": "page_up",
        "h": "focus_chats",
        "<Left>": "focus_chats",
        "r": "reply",
        "e": "edit",
        "dd": "delete",
        "yy": "yank",
        "K": "profile",
        "gp": "profile",
        "gP": "chat_profile",
        "o": "open_media",
        "<CR>": "open_media",
        "gr": "goto_reply",
        "<C-o>": "jump_back",
        "R": "reload_messages",
    },
}


# Названия групп (префиксов) для окна подсказок WhichKey.
KEY_GROUPS: dict[str, str] = {
    "<Space>": "лидер",
    "<Space>w": "панели",
    "<Space>p": "профиль",
    "<Space>R": "обновить",
    "<Space>l": "реакция",
    "<Space>q": "выход",
    "g": "переход",
    "Z": "выход",
    "d": "удалить",
    "y": "копировать",
}


# Описания действий для экрана справки («?»).
ACTION_HELP: dict[str, str] = {
    "command_line": "командная строка (:q, :open …)",
    "search": "поиск: чаты / сообщения",
    "search_next": "следующее совпадение",
    "search_prev": "предыдущее совпадение",
    "help": "эта справка",
    "toggle_pane": "переключить панель",
    "focus_chats": "к списку чатов",
    "focus_messages": "к сообщениям",
    "toggle_chat_list": "скрыть / показать список чатов",
    "find_chat": "найти чат (фильтр списка)",
    "my_profile": "свой профиль",
    "theme": "сменить тему (предпросмотр на j/k)",
    "insert": "написать сообщение (INSERT)",
    "quit": "выход",
    "cancel": "сбросить фильтр/поиск",
    "cursor_down": "вниз (с счётчиком: 5j)",
    "cursor_up": "вверх (у верхнего края подгружает историю)",
    "cursor_first": "в начало (5gg — на пятую строку)",
    "cursor_last": "в конец",
    "half_page_down": "полстраницы вниз",
    "half_page_up": "полстраницы вверх",
    "page_down": "страница вниз",
    "page_up": "страница вверх",
    "open_chat": "открыть чат",
    "profile": "профиль (чата / автора сообщения)",
    "chat_profile": "профиль текущего чата",
    "reload_chats": "перезагрузить список чатов",
    "reload_messages": "перезагрузить сообщения",
    "reply": "ответить на сообщение",
    "edit": "редактировать своё сообщение",
    "delete": "удалить сообщение",
    "yank": "скопировать текст сообщения",
    "open_media": "открыть картинку на весь экран",
    "jump_back": "назад по переходам",
    "jump_forward": "вперёд по переходам",
    "paste": "вставить из буфера: картинку — вложением, текст — в поле ввода",
    "react": "все реакции (поиск)",
    "unreact": "снять свою реакцию",
    "goto_reply": "к исходному сообщению",
}


def action_help(action: str) -> str:
    """Описание действия для справки и WhichKey; понимает «react:🤡»."""
    name, _, arg = action.partition(":")
    if name == "react" and arg:
        from telega.reactions import display_emoji, reaction_name

        return f"{display_emoji(arg)}  {reaction_name(arg)}"
    return ACTION_HELP.get(name, action)
