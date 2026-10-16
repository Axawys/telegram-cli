"""Экран входа: телефон → код → (пароль 2FA), либо QR-код → (пароль 2FA)."""

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
from telega.models import BackendError, CodeDelivery, InvalidApiCredentials, PasswordRequired
from telega.ui.qr import qr_text

log = logging.getLogger(__name__)

# Сколько ждать ответа Telegram на каждом шаге входа.
STEP_TIMEOUT = 60

_STEPS = {
    "phone": ("Номер телефона в международном формате", "+79001234567", False),
    "code": ("Код входа", "12345", False),
    "password": ("Пароль двухфакторной аутентификации", "", True),
    "qr": ("Вход по QR-коду", "", False),
}

QR_HELP = (
    "Откройте Telegram на телефоне → Настройки → Устройства → «Подключить устройство» "
    "и наведите камеру на код. Код сам обновляется каждые ~30 с.\nEsc — назад к вводу номера."
)


class LoginScreen(Screen):
    BINDINGS = [
        Binding("ctrl+e", "change_api", "Изменить api_id/api_hash", show=False),
        Binding("ctrl+r", "resend", "Прислать код иначе", show=False),
        Binding("ctrl+l", "qr", "Вход по QR-коду", show=False),
        Binding("escape", "back", "К вводу номера", show=False),
    ]

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
    #login-delivery { height: auto; margin-bottom: 1; }
    #login-qr { width: auto; height: auto; display: none; }
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
        self.delivery: CodeDelivery | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="login-box"):
            yield Static("Вход в Telegram", id="login-title")
            yield Static(id="login-delivery")
            yield Static(id="login-hint")
            yield Input(id="login-input")
            yield Static(id="login-qr")
            yield Static(id="login-error")
            yield Static("Ctrl+E — изменить api_id / api_hash · Ctrl+Q — выход", id="login-hint-keys")

    def action_change_api(self) -> None:
        self.post_message(self.ChangeApiCredentials())

    def on_mount(self) -> None:
        self._show_step("phone")

    def action_back(self) -> None:
        if self.step in ("code", "password", "qr"):
            self.workers.cancel_group(self, "qr")
            self.delivery = None
            self._show_step("phone")

    # --- вход по QR-коду ---

    def action_qr(self) -> None:
        if self.step in ("phone", "code"):
            self._show_step("qr")
            self._qr_loop()

    @work(exclusive=True, group="qr")
    async def _qr_loop(self) -> None:
        """Показывать QR, пока его не отсканируют; истёкший токен — обновить."""
        while self.step == "qr":
            try:
                url = await asyncio.wait_for(self.backend.qr_login_url(), STEP_TIMEOUT)
            except (TimeoutError, BackendError) as exc:
                self._error(str(exc) or f"Telegram не ответил за {STEP_TIMEOUT} с. Esc — назад")
                return
            self.query_one("#login-qr", Static).update(qr_text(url))
            self.query_one("#login-error", Static).update("")
            try:
                done = await self.backend.wait_qr_login()
            except PasswordRequired:
                self._show_step("password")
                return
            except BackendError as exc:
                self._error(f"{exc}. Esc — назад")
                return
            if done:
                log.info("login: вход по QR-коду")
                self.post_message(self.LoggedIn())
                return

    def action_resend(self) -> None:
        if self.step == "code":
            self._resend()

    @work(exclusive=True, group="resend")
    async def _resend(self) -> None:
        self.query_one("#login-error", Static).update("Просим Telegram прислать код иначе…")
        try:
            delivery = await asyncio.wait_for(self.backend.resend_code(), STEP_TIMEOUT)
        except TimeoutError:
            self._error(f"Telegram не ответил за {STEP_TIMEOUT} с")
            return
        except BackendError as exc:
            self._error(str(exc))
            return
        self.delivery = delivery
        self._show_step("code")

    def _delivery_text(self) -> str:
        if self.step == "qr":
            return QR_HELP
        if self.step == "phone":
            return "Или Ctrl+L — войти по QR-коду: без SMS и кода, нужен Telegram на телефоне."
        d = self.delivery
        if self.step != "code" or d is None:
            return ""
        digits = f" ({d.length} цифр)" if d.length else ""
        lines = [f"Код отправлен {d.where}{digits}."]
        if d.next_way:
            after = f", можно через {d.resend_after} с" if d.resend_after else ""
            lines.append(f"Не пришёл? Ctrl+R — прислать {d.next_way}{after}.")
        lines.append("Код так и не пришёл? Ctrl+L — войти по QR-коду.")
        lines.append("Esc — изменить номер.")
        return "\n".join(lines)

    def _show_step(self, step: str) -> None:
        self.step = step
        hint, placeholder, password = _STEPS[step]
        self.query_one("#login-hint", Static).update(hint)
        self.query_one("#login-delivery", Static).update(self._delivery_text())
        field = self.query_one("#login-input", Input)
        field.value = ""
        field.placeholder = placeholder
        field.password = password
        field.disabled = False
        field.display = step != "qr"
        self.query_one("#login-qr", Static).display = step == "qr"
        if step == "qr":
            self.query_one("#login-qr", Static).update("получаем код…")
        else:
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
                self.delivery = await self.backend.send_code(value)
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
