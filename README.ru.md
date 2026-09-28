# telegram-cli

[English](README.md) · **Русский**

Терминальный клиент Telegram с vim-подобным управлением и картинками прямо в терминале. Команда запуска — `telega`.

> Неофициальный клиент. Проект не связан с Telegram и не одобрен им. Работает через официальный [Telegram API](https://core.telegram.org/api) с вашими собственными `api_id` / `api_hash`.

- **vim-управление**: режимы NORMAL / INSERT / COMMAND, счётчики (`5j`), последовательности (`gg`, `dd`, `yy`), `:команды`, `/поиск`.
- **Картинки**: фото в сообщениях и постах каналов, большая аватарка в профиле. Kitty использует Terminal Graphics Protocol, foot — Sixel. Протокол выбирается автоматически.
- **GIF и стикеры** (прототип): анимированные (`.tgs`), видео (`.webm` с прозрачностью) и обычные (`.webp`). Анимируется выделенное сообщение, `o` открывает анимацию на весь экран.
- **Упоминания**: подсветка @упоминаний, #хештегов и ссылок, автодополнение участников чата при наборе `@`, корректные упоминания пользователей без username.
- Ответы, редактирование, удаление, копирование, профили, фильтр чатов, поиск по сообщениям, скрываемый список чатов.
- **Демо-режим** (`--demo`) без аккаунта и сети.

Стек: Python 3.12+, [Telethon](https://github.com/LonamiWebs/Telethon) (MTProto), [Textual](https://textual.textualize.io/) (TUI), [textual-image](https://github.com/lnqs/textual-image) (kitty / sixel), [PyAV](https://github.com/PyAV-Org/PyAV) и [rlottie-python](https://github.com/laggykiller/rlottie-python) (анимации).

## Установка

Нужен Python 3.12 или новее. Остальные зависимости ставятся через pip, ffmpeg встроен в PyAV.

```bash
git clone https://github.com/Axawys/telegram-cli.git
cd telegram-cli
python3 -m venv .venv
.venv/bin/pip install -e .
```

Запуск: `.venv/bin/telega`. Чтобы команда `telega` работала из любого места:

```bash
ln -s "$PWD/.venv/bin/telega" ~/.local/bin/telega
```

## Первый запуск

Запустите `telega`. Если ключи API ещё не заданы, откроется экран настройки:

1. На нём есть пошаговая инструкция, как получить `api_id` и `api_hash` на <https://my.telegram.org/apps>. `Ctrl+O` открывает сайт в браузере.
2. Вставьте оба значения в поля. `Enter` переходит к следующему полю, а на последнем сохраняет.
3. Ключи сохраняются в `~/.config/telega-cli/config.toml` с правами `600`.
4. Дальше введите телефон, код из Telegram и, если включена двухэтапная проверка, пароль.

Если Telegram не примет ключи, экран настройки откроется снова. На экране входа `Ctrl+E` тоже возвращает к вводу ключей, а `telega --setup` перезапускает настройку. Ключи можно задать и через переменные окружения `TELEGA_API_ID` / `TELEGA_API_HASH`.

Если сайт my.telegram.org при создании приложения показывает «ERROR», заполните все поля латиницей, отключите VPN и блокировщики рекламы, войдите на сайт заново или попробуйте позже.

Сессия хранится в `~/.local/share/telega-cli/telega.session`. **Этот файл даёт полный доступ к аккаунту.** Никому не передавайте его.

Посмотреть интерфейс без аккаунта: `telega --demo`.

## Управление (кратко)

| Клавиши | Действие |
|---|---|
| `j` / `k`, `gg` / `G`, `C-d` / `C-u` | навигация, со счётчиком: `5j` |
| `Enter` / `l` | открыть чат |
| `h`, `Tab` | к списку чатов / переключить панель |
| `C-n`, `:sidebar` | скрыть / показать список чатов |
| `i` / `a` | написать сообщение (INSERT), `Esc` — назад |
| `r` / `e` / `dd` / `yy` | ответить / редактировать / удалить / скопировать |
| `K` | профиль (чата или автора сообщения) с аватаркой |
| `o` / `Enter` на медиа | картинка или анимация на весь экран |
| `/` | фильтр чатов или поиск по сообщениям, `n` / `N` |
| `:open имя`, `:profile`, `:q` | команды |
| `?` | справка |

В INSERT: `@` + буквы открывают подсказку участников; `Tab` / `C-n` / `C-p` листают, `Enter` выбирает. `Enter` отправляет, `Shift+Enter` / `Alt+Enter` / `C-j` переносят строку.

Полный список: [docs/KEYBINDINGS.md](docs/KEYBINDINGS.md).

## Картинки и анимации

| Терминал | Протокол | Анимация |
|---|---|---|
| kitty, ghostty | `tgp` (kitty graphics protocol) | встроенная анимация терминала |
| foot, wezterm, konsole, xterm | `sixel` | смена кадров из приложения |
| остальные | `halfcell` (цветные полублоки) | смена кадров из приложения |

По умолчанию `image_protocol = "auto"`. Разово переопределить можно так: `telega --images sixel`. Отключить: `--images none`. В tmux нужны `allow-passthrough on` и `terminal-features ',*:RGB:sixel'`.

Настройки анимаций: `animations = "selected" | "fullscreen" | "off"` и `kitty_native_animation` (флаг `--no-kitty-anim`). Все параметры описаны в [`config.example.toml`](config.example.toml).

## Файлы

| Путь | Что |
|---|---|
| `~/.config/telega-cli/config.toml` | конфиг |
| `~/.local/share/telega-cli/telega.session` | сессия Telegram |
| `~/.cache/telega-cli/media/` | кэш картинок, анимаций и аватарок (можно удалять) |
| `~/.local/state/telega-cli/telega.log` | лог (`--debug` — подробный) |

## Разработка

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check src tests
```

Документация для разработчиков (на русском):

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): устройство, слои, поток данных.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): окружение, тесты, как добавить функцию, отладка, подводные камни.
- [docs/KEYBINDINGS.md](docs/KEYBINDINGS.md): все клавиши и команды.
- [docs/ROADMAP.md](docs/ROADMAP.md): что сделано, что дальше, известные ограничения.

## Лицензия

[GNU GPL v3.0 или новее](LICENSE). Вы можете свободно использовать, изучать, изменять и распространять программу. Производные работы должны распространяться под той же лицензией и с исходным кодом.
