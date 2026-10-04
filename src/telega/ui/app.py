"""Textual-приложение: запуск, настройка API, авторизация, маршрутизация событий.

Порядок запуска:
  нет api_id/api_hash (или --setup) → ApiSetupScreen → сохранить в config.toml
  → создать бэкенд → connect → не авторизован? LoginScreen → MainScreen
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from textual.app import App, ComposeResult
from textual.message import Message as TMessage
from textual.widgets import Static

from telega.backend import Backend, BackendEvent
from telega.config import Config, ConfigError, save_api_credentials
from telega.ui.screens.login import LoginScreen
from telega.ui.screens.main import MainScreen
from telega.ui.screens.setup import ApiSetupScreen
from telega.ui.themes import apply_theme, register_themes

log = logging.getLogger(__name__)

BackendFactory = Callable[[Config], Backend]

# Сколько ждать подключения к Telegram, прежде чем показать ошибку.
CONNECT_TIMEOUT = 45

CONNECT_HELP = (
    "Возможные причины:\n"
    "  • нет интернета или VPN/прокси переподключается;\n"
    "  • провайдер блокирует Telegram — включите VPN;\n"
    "  • VPN включён, но не пропускает Telegram — попробуйте другой сервер.\n\n"
    "r — повторить    q — выход"
)


class BackendEventMessage(TMessage):
    """Обёртка события бэкенда, чтобы доставить его через очередь Textual."""

    def __init__(self, event: BackendEvent) -> None:
        super().__init__()
        self.event = event


class TelegaApp(App):
    TITLE = "telega-cli"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: $background; }
    #splash { width: 100%; height: 100%; content-align: center middle; color: $text-muted; }
    """

    def __init__(
        self,
        config: Config,
        backend: Backend | None = None,
        *,
        backend_factory: BackendFactory | None = None,
        force_setup: bool = False,
    ) -> None:
        """`backend` — готовый бэкенд (демо, тесты); `backend_factory` — создать его,
        когда станут известны api_id/api_hash (обычный запуск)."""
        super().__init__()
        if backend is None and backend_factory is None:
            raise ValueError("нужен backend или backend_factory")
        self.config = config
        self.backend: Backend | None = None
        self._factory = backend_factory
        self._force_setup = force_setup
        self.main_screen: MainScreen | None = None
        self._connecting = False
        self._connect_failed = False
        self._authorized = False
        register_themes(self)
        apply_theme(self, config.ui.theme)
        if backend is not None:
            self._attach(backend)

    def _attach(self, backend: Backend) -> None:
        self.backend = backend

        def forward(event: BackendEvent) -> None:
            if self.backend is backend:  # события старого бэкенда игнорируем
                self.post_message(BackendEventMessage(event))

        backend.add_listener(forward)

    def compose(self) -> ComposeResult:
        yield Static("Подключение к Telegram…", id="splash")

    def on_mount(self) -> None:
        # Textual в App.run() включает asyncio.eager_task_factory, а Telethon с ним
        # несовместим: его сетевые циклы стартуют синхронно внутри create_task(),
        # раньше чем выставлен флаг _user_connected, видят False и сразу выходят.
        # Итог — вечное «Подключение…». Возвращаем обычную фабрику задач.
        asyncio.get_running_loop().set_task_factory(None)
        if self.backend is None and (self._force_setup or not self.config.has_api_credentials):
            self._show_setup()
        else:
            self._start()

    # --- настройка api_id / api_hash --------------------------------------

    def _show_setup(self, error: str | None = None) -> None:
        tg = self.config.telegram
        self.push_screen(
            ApiSetupScreen(self.config.path, api_id=tg.api_id, api_hash=tg.api_hash, error=error)
        )

    async def on_api_setup_screen_done(self, message: ApiSetupScreen.Done) -> None:
        try:
            path = save_api_credentials(self.config, message.api_id, message.api_hash)
        except (OSError, ConfigError) as exc:
            log.exception("save config")
            # Файл записать не удалось — работаем с ключами в памяти.
            self.config.telegram.api_id = message.api_id
            self.config.telegram.api_hash = message.api_hash
            self.notify(f"Не удалось сохранить конфиг: {exc}", severity="error", timeout=10)
        else:
            log.info("api_id/api_hash сохранены в %s", path)
        await self.pop_screen()
        await self._drop_backend()
        self._start()

    async def on_login_screen_change_api_credentials(
        self, message: LoginScreen.ChangeApiCredentials
    ) -> None:
        if self._factory is None:
            return  # демо-бэкенд без ключей
        await self.pop_screen()
        await self._drop_backend()
        self._show_setup(message.error)

    async def _drop_backend(self) -> None:
        """Отключить бэкенд, созданный со старыми ключами (если он был)."""
        if self.backend is not None and self._factory is not None:
            old, self.backend = self.backend, None
            try:
                await asyncio.wait_for(old.disconnect(), timeout=3)
            except Exception:
                log.exception("disconnect")

    # --- запуск -----------------------------------------------------------

    def _start(self) -> None:
        self.run_worker(self._startup(), exclusive=True, group="startup")

    async def _startup(self) -> None:
        splash = self.query_one("#splash", Static)
        self._connect_failed = False
        started = asyncio.get_running_loop().time()

        def tick() -> None:
            elapsed = int(asyncio.get_running_loop().time() - started)
            splash.update(f"Подключение к Telegram… {elapsed} с")

        tick()
        timer = self.set_interval(1, tick)
        self._connecting = True
        try:
            if self.backend is None:
                assert self._factory is not None
                self._attach(self._factory(self.config))
            assert self.backend is not None
            await asyncio.wait_for(self._connect(self.backend), CONNECT_TIMEOUT)
        except TimeoutError:
            log.warning("connect: нет ответа за %s с", CONNECT_TIMEOUT)
            self._fail_connect(f"Telegram не ответил за {CONNECT_TIMEOUT} с.")
            return
        except Exception as exc:
            log.exception("connect")
            self._fail_connect(f"Не удалось подключиться: {exc}")
            return
        finally:
            timer.stop()
            self._connecting = False
        if self._authorized:
            await self._enter_main()
        else:
            await self.push_screen(LoginScreen(self.backend))

    async def _connect(self, backend: Backend) -> None:
        await backend.connect()
        self._authorized = await backend.is_authorized()

    def _fail_connect(self, reason: str) -> None:
        self._connect_failed = True
        self.query_one("#splash", Static).update(f"{reason}\n\n{CONNECT_HELP}")

    async def _retry_connect(self) -> None:
        await self._drop_backend()
        if self.backend is not None:  # готовый бэкенд (демо) — просто переподключаемся
            try:
                await self.backend.disconnect()
            except Exception:
                log.exception("disconnect")
        self._start()

    async def on_login_screen_logged_in(self, _message: LoginScreen.LoggedIn) -> None:
        await self.pop_screen()
        await self._enter_main()

    async def _enter_main(self) -> None:
        assert self.backend is not None
        await self.backend.load_me()
        self.main_screen = MainScreen(self.backend, self.config)
        await self.push_screen(self.main_screen)

    async def on_backend_event_message(self, message: BackendEventMessage) -> None:
        if self.main_screen is not None:
            try:
                await self.main_screen.handle_backend_event(message.event)
            except Exception:
                log.exception("handle_backend_event")

    async def on_key(self, event) -> None:
        # Заставка: q — выход, r — повторить после ошибки подключения.
        if self.screen is not self.screen_stack[0]:
            return
        if event.key == "q":
            await self.shutdown()
        elif event.key == "r" and self._connect_failed and not self._connecting:
            await self._retry_connect()

    async def shutdown(self) -> None:
        """Корректно отключиться от Telegram и выйти."""
        if self.backend is not None:
            try:
                await asyncio.wait_for(self.backend.disconnect(), timeout=3)
            except Exception:
                log.exception("disconnect")
        self.exit()
