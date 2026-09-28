# telega-cli — заметки для ИИ-ассистентов и контрибьюторов

Терминальный клиент Telegram: Python + Telethon + Textual + textual-image.

Перед изменениями прочитайте:
- `docs/ARCHITECTURE.md`: слои, поток данных, режимы vim, упоминания, картинки.
- `docs/DEVELOPMENT.md`: как добавить действие, команду, метод бэкенда; тесты; соглашения.
- `docs/ROADMAP.md`: что дальше и известные ограничения.

Команды:
- тесты: `.venv/bin/pytest -q`
- демо без аккаунта: `.venv/bin/telega --demo`

Жёсткие правила:
- Типы Telethon не выходят из `src/telega/backend/telethon_backend.py`. UI работает только с `telega.models`.
- Любой новый метод `Backend` реализуется и в `TelethonBackend`, и в `DemoBackend`, и покрывается тестом в `tests/test_ui.py`.
- Новое vim-действие требует `keymap.py` (+`ACTION_HELP`), `MainScreen.vim_<имя>` и `docs/KEYBINDINGS.md`.
- Смещения сущностей в моделях хранятся в индексах Python; UTF-16 встречается только на границе с Telegram (`telega/text.py`).
- `init_images()` вызывается до `App.run()`.
- `TelegaApp.on_mount` выключает eager task factory Textual, иначе Telethon зависает. Не удаляйте это. Pilot-тесты это не покрывают, сетевые изменения проверяйте реальным запуском (см. «Подводные камни» в DEVELOPMENT.md).
- Не перекрывайте внутренние методы Textual (`_render`, `_refresh` …) в своих виджетах и экранах.
- Не коммитьте `*.session`: это полный доступ к аккаунту.

Личные заметки о ходе работы (окружение, на чём остановились) — в `CLAUDE.local.md`:
он загружается автоматически и не коммитится (см. `.gitignore`).
