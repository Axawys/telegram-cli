# Разработка

## Окружение

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q            # все тесты, около 10 с
.venv/bin/ruff check src tests # статический анализ
.venv/bin/telega --demo        # интерфейс без аккаунта
```

Python 3.12+ (проверено на 3.14).

Пользовательская установка — `install.sh` (pipx, zip-архив ветки с GitHub, git не нужен). Проверить скрипт, не трогая свою систему:

```bash
SP=$(mktemp -d)
PIPX_HOME=$SP/pipx PIPX_BIN_DIR=$SP/bin PATH="$SP/bin:$PATH" sh install.sh .
```

`PATH` с `$SP/bin` нужен, чтобы скрипт не вызвал `pipx ensurepath` и не правил ваш `~/.bashrc`. Зависимости перечислены в `pyproject.toml`.

## Структура

```
src/telega/
  __main__.py            CLI, логирование, init_images, запуск
  config.py              TOML-конфиг, XDG-пути, env TELEGA_API_ID/HASH,
                         проверка и сохранение api_id/api_hash
  models.py              Chat, Message, User, Profile, TextEntity …
  text.py                UTF-16 ⇄ индексы Python, shorten()
  mentions.py            поиск «@запроса», вставка, разбор упоминаний при отправке
  vim/keys.py            Mode, KeyParser, parse_sequence, token_from_event
  vim/keymap.py          DEFAULT_KEYMAP, ACTION_HELP
  backend/base.py        Backend (ABC) + события
  backend/telethon_backend.py
  backend/demo.py
  ui/app.py              TelegaApp
  ui/render.py           Rich-рендер сообщений и строк чатов
  ui/screens/main.py     MainScreen — центральная логика
  ui/screens/modals.py   Profile / ImageViewer / Help / Confirm
  ui/screens/login.py    телефон → код → 2FA
  ui/screens/setup.py    первый запуск: инструкция и ввод api_id / api_hash
  ui/widgets/            chat_list, message_view, composer, status, image,
                         animated, which_key (окно подсказок лидера)
tests/
  test_keys.py test_mentions.py test_text.py test_config.py   чистая логика
  test_ui.py      сквозные тесты UI на DemoBackend (Pilot)
  test_setup.py   первый запуск: ввод ключей, сохранение, повтор при отказе
```

## Тесты

- Чистая логика (`mentions`, `vim/keys`, `text`) покрывается обычными unit-тестами. Новую логику лучше сразу выносить в такие модули.
- UI проверяется через `app.run_test()` + `pilot.press(...)` на `DemoBackend` (см. `tests/test_ui.py`). Если функции нужны данные, добавьте их в `DemoBackend._build()`.
- В тестах вызывается `init_images("unicode")`, потому что настоящего терминала нет.
- Реального Telegram в тестах нет. Изменения в `telethon_backend.py` проверяйте вручную на своём аккаунте, лучше на тестовом.

### Скриншот интерфейса без терминала

```python
async with app.run_test(size=(130, 42)) as pilot:
    ...
    app.save_screenshot("shot.svg")
```

SVG открывается в браузере. Картинки на нём видны только в режимах `halfcell` / `unicode`.

### Экран первого запуска без реальных ключей

```bash
XDG_CONFIG_HOME=/tmp/telega-cfg .venv/bin/telega --setup
```

Ключи сохранятся во временный каталог, а не в ваш конфиг.

### Проверка графики в реальном терминале

```bash
foot  -e .venv/bin/telega --demo --images sixel
kitty -e .venv/bin/telega --demo --images tgp
```

Откройте канал «Фото природы» (`:open фото`) и профиль (`K`).

## Как добавить…

### vim-действие

1. `vim/keymap.py`: добавьте `"<клавиши>": "имя"` в нужный контекст и описание в `ACTION_HELP`.
2. `ui/screens/main.py`: `def vim_имя(self, a: Action)` (может быть `async`). `a.count` и `a.has_count` — счётчик.
3. `docs/KEYBINDINGS.md`.
4. Тест в `tests/test_ui.py`.

### `:команду`

Добавьте ветку в `MainScreen.run_command()` (`match cmd:`), строку в `HelpScreen._keys_table()` и в `docs/KEYBINDINGS.md`.

### Метод бэкенда

1. Абстрактный метод в `backend/base.py`, возвращающий модели из `models.py`.
2. Реализации в `telethon_backend.py` **и** в `demo.py`.
3. Если Telegram может присылать новое событие, добавьте dataclass в `base.py`, включите его в `BackendEvent`, зарегистрируйте в `TelethonBackend._install_handlers` и обработайте в `MainScreen.handle_backend_event`.

### Новый тип медиа

`TelethonBackend._describe_media()` возвращает `(MediaKind, подпись)`. Если медиа нужно рисовать картинкой, добавьте тип в `IMAGE_KINDS` (`models.py`) и научите `download_image()` его скачивать.

## Отладка

- Лог: `~/.local/state/telega-cli/telega.log`, подробный — `telega --debug`.
- Консоль Textual: в одном терминале `textual console` (нужен `pip install textual-dev`), в другом `.venv/bin/textual run --dev telega.__main__:main -- --demo`. Там видны `self.log(...)` и события.
- Если клавиши в NORMAL «не работают», скорее всего фокус достался какому-то виджету. Смотрите `app.focused`: в NORMAL он должен быть `None`.

## Соглашения

- Интерфейс и комментарии на русском, идентификаторы на английском.
- Типы Telethon не выходят из `telethon_backend.py`.
- Сетевые операции в UI выполняются через `@work` или `run_worker`, event loop не блокируется. Ошибки для пользователя передаются как `BackendError(текст)` и показываются в статусной строке.
- Все смещения сущностей в моделях хранятся в индексах Python. UTF-16 встречается только на границе с Telegram.
- Не называйте методы виджетов и экранов `_render`, `_refresh`, `render_*` и т. п.: это перекрывает внутренние методы Textual.

## Подводные камни

- **Eager task factory.** `App.run()` в Textual включает `asyncio.eager_task_factory`, а `app.run_test()` — нет. Telethon с eager-задачами молча зависает на «Подключение…»: его сетевые циклы стартуют прямо внутри `create_task()`, видят `_user_connected == False` и завершаются. `TelegaApp.on_mount` возвращает обычную фабрику (`set_task_factory(None)`), регрессию ловит `test_eager_task_factory_is_disabled`. Важный вывод: зелёные тесты на Pilot **не гарантируют**, что приложение работает в настоящем терминале. Сетевые изменения проверяйте реальным запуском.
- **Диагностика зависаний.** Смотрите `telega.log` с `--debug`. Для полного лога Telethon временно поставьте логгеру `telethon` уровень DEBUG. Если после «Starting send loop» нет строк «Assigned msg_id…», сетевые задачи Telethon не работают.
