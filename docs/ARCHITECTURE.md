# Архитектура

## Слои

```
┌──────────────────────────── UI (Textual) ─────────────────────────────┐
│ ui/app.py           TelegaApp: запуск, логин, маршрутизация событий    │
│ ui/screens/main.py  MainScreen: vim-диспетчер, действия, команды       │
│ ui/screens/*.py     ApiSetup, Login, Profile, ImageViewer, Help, …     │
│ ui/widgets/*.py     ChatList, MessageView, Composer, StatusLine, image │
│ ui/render.py        модели → Rich Text (чистые функции)                │
└──────────────┬─────────────────────────────────────────▲──────────────┘
               │ async-вызовы                            │ BackendEvent
┌──────────────▼──────────── backend/base.py ────────────┴──────────────┐
│ Backend (ABC): get_chats, get_messages, send_message, search_members,  │
│ download_image, download_avatar, get_profile … + add_listener()        │
├───────────────────────────────┬───────────────────────────────────────┤
│ backend/telethon_backend.py   │ backend/demo.py                       │
│ настоящий Telegram (MTProto)  │ фейковые данные, Pillow-картинки      │
└───────────────────────────────┴───────────────────────────────────────┘
  Общие модули без зависимостей от UI и Telethon:
  models.py (dataclass-модели) · mentions.py (@теги) · text.py (UTF-16)
  vim/keys.py (парсер клавиш) · vim/keymap.py (раскладка) · config.py
```

**Главное правило:** типы Telethon не выходят за пределы `telethon_backend.py`. UI работает только с `telega.models`. Поэтому UI тестируется на `DemoBackend`, а бэкенд можно заменить (например, на TDLib), не трогая интерфейс.

## Поток данных

### Запуск

1. `__main__.main()` читает конфиг (`config.py`) и настраивает лог в файл. stdout занят TUI, поэтому лог пишется только в файл.
2. `init_images(protocol)` вызывается **до** `App.run()`: textual-image определяет графику терминала запросами через stdin/stdout, а после старта Textual это уже невозможно.
3. Если `api_id`/`api_hash` не заданы или указан `--setup`, открывается `ApiSetupScreen` (`ui/screens/setup.py`) с инструкцией и полями ввода. По сообщению `Done` `TelegaApp` вызывает `config.save_api_credentials()`. Функция точечно правит секцию `[telegram]` в `config.toml`, сохраняя комментарии и остальные секции, и выставляет права 600.
4. Бэкенд создаётся **фабрикой** (`TelegaApp(config, backend_factory=TelethonBackend)`) только после того, как ключи известны. Демо и тесты передают готовый `backend=`.
5. `TelegaApp._startup()`: `backend.connect()` → `is_authorized()` → `LoginScreen` или сразу `MainScreen`. Если Telegram отверг ключи (`InvalidApiCredentials` при `send_code`) или на экране входа нажат `Ctrl+E`, старый бэкенд отключается и снова открывается `ApiSetupScreen` с прежними значениями.
6. `backend.load_me()` заполняет `backend.me` и включает обработчики событий Telethon.

### Входящие события

```
Telethon handler ─► Backend._emit(NewMessageEvent) ─► listener в TelegaApp
  ─► post_message(BackendEventMessage) ─► TelegaApp.on_backend_event_message
  ─► MainScreen.handle_backend_event ─► ChatList.upsert / MessageView.append_message
```

Telethon и Textual работают в одном asyncio-цикле, потоков нет. Фабрика задач обычная: eager-фабрику, которую включает Textual, приложение выключает при старте, так как Telethon с ней не работает. События проходят через очередь сообщений Textual, поэтому UI обновляется в своём порядке.

Обработчики **идемпотентны**: одно и то же сообщение может прийти и как результат `send_message`, и как событие. `MessageView.append_message` игнорирует уже известные id.

### Картинки

- `Message.has_image` равен True для `PHOTO` и `IMAGE` (картинка-документ, кроме webp-стикеров).
- `MainScreen._schedule_images()` запускает воркеры, одновременно не больше 3 (`_IMAGE_CONCURRENCY`). Первыми идут свежие сообщения.
- `backend.download_image()` кладёт файл в `~/.cache/telega-cli/media/<chat>_<msg>.<ext>` и при повторном запросе отдаёт его из кэша.
- `MessageItem.set_image(path)` монтирует виджет из `make_image()`. Класс виджета выбирается по протоколу: TGP, Sixel, Halfcell или Unicode.
- Аватарки загружаются **только** в `ProfileScreen`, файл `media/avatars/<peer>_<photo_id>`. В списке чатов их нет намеренно: так решено на текущем этапе.

### Упоминания (@теги)

`mentions.py` не зависит от UI и Telegram:

1. `Composer` на каждое изменение текста или курсора вызывает `find_query(text, cursor)`. Функция проверяет, набирается ли сейчас `@запрос`, и отсекает e-mail.
2. `MainScreen._search_mentions` — exclusive-воркер с debounce 150 мс, вызывает `backend.search_members()`:
   - в группах до 200 участников все участники загружаются один раз и фильтруются локально;
   - в больших группах поиск идёт на сервере;
   - если список участников скрыт (`ChatAdminRequired`), кандидатами становятся авторы загруженных сообщений.
3. При выборе `apply_completion()` вставляет `@username` или имя пользователя без username и запоминает `Mention`.
4. При отправке `resolve_mentions()` заново ищет метки в тексте, ведь текст могли отредактировать. Бэкенд превращает найденное в сущности `MessageEntityMention` / `InputMessageEntityMentionName` со смещениями в **UTF-16** (`text.py`).

Входящие сущности конвертируются в обратную сторону, из UTF-16 в индексы Python, и подсвечиваются в `render.message_body()`.

### vim-режимы

| Режим | Фокус | Кто обрабатывает клавиши |
|---|---|---|
| NORMAL | ни у кого | `MainScreen.on_key` → `KeyParser.feed()` → `vim_<действие>()` |
| INSERT | `Composer` | `Composer._on_key` (Enter, Esc, подсказки), остальное — TextArea |
| COMMAND / SEARCH | `CommandLine` | `CommandLine._on_key` → `Finished` / `Edited` |

`ChatList` и `MessageView` созданы с `can_focus=False`: курсоры в них двигает диспетчер. `Composer` и `CommandLine` получают `can_focus=True` только в своих режимах. Иначе Textual сам отдаёт им фокус, и NORMAL-режим перестаёт получать клавиши.

`KeyParser` ищет последовательность сначала в контексте активной панели (`chats` / `messages`), потом в `global`. Префикс (`g` перед `gg`) ждёт следующую клавишу. Неизвестная последовательность сбрасывает буфер.

Темы — `ui/themes.py`: каждая тема задаёт Theme Textual и ANSI-палитру. Именованные цвета Rich (`cyan`, `bold yellow`, цвета имён отправителей) Textual переводит в RGB по этой палитре, поэтому в виджетах лучше писать именованные цвета, а не hex: тогда они следуют теме. Новая тема добавляется в `SPECS` и в `config.THEMES`.

Окно подсказок `WhichKey` (`ui/widgets/which_key.py`) показывает `KeyParser.continuations()` для начатого префикса: после лидера `<Space>` сразу, после остальных префиксов — с задержкой `_WHICH_KEY_DELAY`, чтобы не мигать на быстром `gg`. Окно стоит в потоке раскладки, а не поверх ленты: sixel/kitty-картинки плохо уживаются с перекрывающими слоями.

## Модели (`models.py`)

- `Chat.id` — «marked» peer id, как в Telethon: пользователь > 0, обычная группа < 0, канал или супергруппа — `-100…`.
- `Message.entities[*].offset` хранятся в индексах Python-строки, а не в UTF-16.
- `Message.media` + `media_label`: тип медиа и человекочитаемая подпись. Непросматриваемые медиа (видео, голосовые, файлы) пока показываются только подписью.

## Почему такие библиотеки

- **Telethon**, а не TDLib: чистый Python, ставится через pip, без сборки нативной библиотеки, активно поддерживается (1.45, сентябрь 2026). Минус: локальной БД сообщений нет, история каждый раз запрашивается с сервера. Кэш entity хранится в session-файле.
- **Textual**: зрелый async TUI-фреймворк с CSS, тестовым Pilot и скриншотами.
- **textual-image**: единственная живая интеграция kitty и sixel с Textual. Ограничение: sixel может мерцать при прокрутке (см. ROADMAP).
