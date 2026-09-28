"""Экран входа: телефон → код → (пароль 2FA)."""

from __future__ import annotations

import asyncio
import logging

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message as TMessage
from textual.screen import Screen
from textual.widgets import Input, Static

from telega.backend import Backend
from telega.models import BackendError, InvalidApiCredentials, PasswordRequired

log = logging.getLogger(__name__)

# Сколько ждать ответа Telegram на каждом шаге входа.
STEP_TIMEOUT = 60

_STEPS = {
    "phone": ("Номер телефона в международном формате", "+79001234567", False),
    "code": ("Код из Telegram (придёт в приложение или SMS)", "12345", False),
    "password": ("Пароль двухфакторной аутентификации", "", True),
}


class LoginScreen(Screen):
    BINDINGS = [Binding("ctrl+e", "change_api", "Изменить api_id/api_hash", show=False)]

    DEFAULT_CSS = """
    LoginScreen { align: center middle; }
    #login-box {
        width: 60;
        height: auto;
        border: round $accent;
        padding: 1 2;
    }
    #login-title { text-style: bold; margin-bottom: 1; }
    #login-error { color: $error; height: auto; margin-top: 1; }
    #login-hint-keys { color: $text-muted; margin-top: 1; }
    """

    class LoggedIn(TMessage):
        pass

    class ChangeApiCredentials(TMessage):
        """Вернуться к вводу api_id/api_hash (сами попросили или Telegram их отверг)."""

        def __init__(self, error: str | None = None) -> None:
            super().__init__()
            self.error = error

    def __init__(self, backend: Backend) -> None:
        super().__init__()
        self.backend = backend
        self.step = "phone"

    def compose(self) -> ComposeResult:
        with Vertical(id="login-box"):
            yield Static("Вход в Telegram", id="login-title")
            yield Static(id="login-hint")
            yield Input(id="login-input")
            yield Static(id="login-error")
            yield Static("Ctrl+E — изменить api_id / api_hash · Ctrl+Q — выход", id="login-hint-keys")

    def action_change_api(self) -> None:
        self.post_message(self.ChangeApiCredentials())

    def on_mount(self) -> None:
        self._show_step("phone")

    def _show_step(self, step: str) -> None:
        self.step = step
        hint, placeholder, password = _STEPS[step]
        self.query_one("#login-hint", Static).update(hint)
        field = self.query_one("#login-input", Input)
        field.value = ""
        field.placeholder = placeholder
        field.password = password
        field.disabled = False
        field.focus()
        self.query_one("#login-error", Static).update("")

    @on(Input.Submitted, "#login-input")
    def _submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value:
            event.input.disabled = True
            self.query_one("#login-error", Static).update("")
            self._advance(value)

    @work(exclusive=True)
    async def _advance(self, value: str) -> None:
        try:
            await asyncio.wait_for(self._run_step(value), STEP_TIMEOUT)
        except TimeoutError:
            log.warning("login: шаг %s без ответа %s с", self.step, STEP_TIMEOUT)
            self._error(
                f"Telegram не ответил за {STEP_TIMEOUT} с. Проверьте интернет/VPN "
                "и нажмите Enter ещё раз."
            )
        except InvalidApiCredentials as exc:
            self.post_message(self.ChangeApiCredentials(f"{exc}. Проверьте значения и введите заново."))
        except BackendError as exc:
            self._error(str(exc))
        except Exception as exc:
            log.exception("login")
            self._error(f"{type(exc).__name__}: {exc}")

    async def _run_step(self, value: str) -> None:
        self.query_one("#login-error", Static).update("Ждём ответа Telegram…")
        match self.step:
            case "phone":
                await self.backend.send_code(value)
                self._show_step("code")
            case "code":
                try:
                    await self.backend.sign_in_code(value)
                except PasswordRequired:
                    self._show_step("password")
                    return
                self.post_message(self.LoggedIn())
            case "password":
                await self.backend.sign_in_password(value)
                self.post_message(self.LoggedIn())

    def _error(self, text: str) -> None:
        self.query_one("#login-error", Static).update(text)
        field = self.query_one("#login-input", Input)
        field.disabled = False
        field.focus()
