"""Раскладка по умолчанию для NORMAL-режима.

Контексты:
  global   — действует всегда (если не переопределено в контексте панели)
  chats    — фокус на списке чатов
  messages — фокус на ленте сообщений

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
        "i": "insert",
        "a": "insert",
        "ZZ": "quit",
        "ZQ": "quit",
        "n": "search_next",
        "N": "search_prev",
        "<Esc>": "cancel",
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
        "R": "reload_messages",
    },
}


# Описания действий для экрана справки («?»).
ACTION_HELP: dict[str, str] = {
    "command_line": "командная строка (:q, :open, :profile …)",
    "search": "поиск: фильтр чатов / поиск по сообщениям",
    "search_next": "следующее совпадение",
    "search_prev": "предыдущее совпадение",
    "help": "эта справка",
    "toggle_pane": "переключить панель",
    "focus_chats": "к списку чатов",
    "focus_messages": "к сообщениям",
    "toggle_chat_list": "скрыть / показать список чатов",
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
    "goto_reply": "перейти к сообщению, на которое ответили",
}
