"""Первый запуск: инструкция по получению api_id / api_hash и их ввод.

Показывается, если ключи не заданы ни в config.toml, ни в переменных
окружения (или по `telega --setup`, или если Telegram их отверг).
Сохранение в файл делает TelegaApp по сообщению `Done`.
"""

from __future__ import annotations

from pathlib import Path

from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, VerticalScroll
from textual.message import Message as TMessage
from textual.screen import Screen
from textual.widgets import Input, Label, Static

from telega.config import ConfigError, validate_api_credentials

MY_TELEGRAM_URL = "https://my.telegram.org/apps"


def _instructions() -> Text:
    link = Style(color="cyan", underline=True, link=MY_TELEGRAM_URL)
    t = Text()
    t.append(
        "Каждому стороннему клиенту Telegram нужны свои ключи API. Их получают один раз, "
        "бесплатно, на официальном сайте Telegram.\n\n"
    )
    steps: list[list[tuple[str, Style | str]]] = [
        [("Откройте ", ""), (MY_TELEGRAM_URL, link), ("  (Ctrl+O — открыть в браузере)", "dim")],
        [("Введите свой номер телефона. Код подтверждения придёт ", ""),
         ("в приложение Telegram", "bold"), (", а не по SMS.", "")],
        [("Откройте раздел ", ""), ("API development tools", "bold"),
         (" — ссылка на главной странице сайта. Если случайно ушли с формы, "
          "просто вернитесь по этой ссылке.", "")],
        [("Заполните форму ", ""), ("Create new application", "bold"),
         (" — без неё ключи не выдаются (если приложение уже создано — "
          "сразу переходите к шагу 5):\n", ""),
         ("     App title:   ", "dim"), ("любое, например telega-cli\n", ""),
         ("     Short name:  ", "dim"), ("5–32 латинских букв/цифр без пробелов, например telegacli\n", ""),
         ("     Platform:    ", "dim"), ("Desktop\n", ""),
         ("     URL, Description можно оставить пустыми. Нажмите ", "dim"),
         ("Create application", "bold"), (".", "dim")],
        [("На странице приложения, в блоке ", ""), ("App configuration", "bold"),
         (", скопируйте ", ""), ("App api_id", "bold"), (" (число) и ", ""),
         ("App api_hash", "bold"), (" (32 символа) и вставьте ниже.", "")],
    ]
    for n, parts in enumerate(steps, 1):
        t.append(f"{n}. ", style="bold yellow")
        for chunk, style in parts:
            t.append(chunk, style=style)
        t.append("\n")
    t.append(
        "\napi_hash — секрет вашего приложения: не публикуйте его. Если сайт пишет «ERROR» "
        "при создании приложения, попробуйте другой Short name или отключите VPN/блокировщик.",
        style="dim",
    )
    return t


class ApiSetupScreen(Screen):
    AUTO_FOCUS = "#api-id"

    BINDINGS = [
        Binding("ctrl+o", "open_site", "Открыть сайт", show=False),
    ]

    DEFAULT_CSS = """
    ApiSetupScreen { align: center top; }
    #setup-box {
        width: 90;
        max-width: 100%;
        height: auto;
        max-height: 100%;
        border: round $accent;
        padding: 0 2;
        margin-top: 1;
    }
    #setup-title { text-style: bold; margin: 1 0; }
    #setup-box Label { margin-top: 1; text-style: bold; }
    #setup-error { color: $error; height: auto; margin-top: 1; }
    #setup-hint { color: $text-muted; margin: 1 0; }
    """

    class Done(TMessage):
        def __init__(self, api_id: int, api_hash: str) -> None:
            super().__init__()
            self.api_id = api_id
            self.api_hash = api_hash

    def __init__(
        self,
        config_path: Path,
        *,
        api_id: int | None = None,
        api_hash: str | None = None,
        error: str | None = None,
    ) -> None:
        super().__init__()
        self.config_path = config_path
        self._api_id = api_id
        self._api_hash = api_hash
        self._error = error

    def compose(self) -> ComposeResult:
        with Center():
            with VerticalScroll(id="setup-box"):
                yield Static("Настройка доступа к Telegram API", id="setup-title")
                yield Static(_instructions(), id="setup-instructions")
                yield Label("api_id")
                yield Input(
                    str(self._api_id or ""),
                    placeholder="1234567",
                    restrict=r"[0-9]*",
                    max_length=12,
                    id="api-id",
                )
                yield Label("api_hash")
                yield Input(
                    self._api_hash or "",
                    placeholder="32 символа: 0123456789abcdef…",
                    restrict=r"[0-9a-fA-F]*",
                    max_length=32,
                    id="api-hash",
                )
                yield Static(self._error or "", id="setup-error")
                yield Static(
                    f"Enter — далее / сохранить · Tab — между полями · Ctrl+Q — выход\n"
                    f"Ключи сохранятся в {self.config_path} (права 600).",
                    id="setup-hint",
                )

    def action_open_site(self) -> None:
        self.app.open_url(MY_TELEGRAM_URL)

    def _show_error(self, text: str) -> None:
        self.query_one("#setup-error", Static).update(text)

    @on(Input.Submitted, "#api-id")
    def _id_submitted(self, event: Input.Submitted) -> None:
        if not event.value.strip():
            self._show_error("Введите api_id")
            return
        self._show_error("")
        self.query_one("#api-hash", Input).focus()

    @on(Input.Submitted, "#api-hash")
    def _hash_submitted(self) -> None:
        api_id = self.query_one("#api-id", Input).value
        api_hash = self.query_one("#api-hash", Input).value
        try:
            parsed_id, parsed_hash = validate_api_credentials(api_id, api_hash)
        except ConfigError as exc:
            self._show_error(str(exc))
            self.query_one("#api-id" if "api_id" in str(exc) else "#api-hash", Input).focus()
            return
        self._show_error("")
        self.post_message(self.Done(parsed_id, parsed_hash))
