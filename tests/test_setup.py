"""Первый запуск: ввод api_id / api_hash в терминале."""

from __future__ import annotations

import asyncio
import tomllib

from telega.backend.demo import DemoBackend
from telega.config import Config
from telega.models import InvalidApiCredentials
from telega.ui.app import TelegaApp
from telega.ui.screens.login import LoginScreen
from telega.ui.screens.main import MainScreen
from telega.ui.screens.setup import ApiSetupScreen
from telega.ui.widgets.image import init_images

HASH = "0123456789abcdef0123456789abcdef"


class RejectingBackend(DemoBackend):
    """Не авторизован, а Telegram отвергает ключи при отправке кода."""

    async def is_authorized(self) -> bool:
        return False

    async def send_code(self, phone: str) -> None:
        raise InvalidApiCredentials("Telegram не принял api_id / api_hash")


async def _wait_for(pilot, screen_type, attempts: int = 50):
    for _ in range(attempts):
        await pilot.pause(0.02)
        if isinstance(pilot.app.screen, screen_type):
            return pilot.app.screen
    raise AssertionError(f"не дождались {screen_type.__name__}, сейчас {pilot.app.screen!r}")


async def test_setup_saves_credentials_and_starts(tmp_path):
    init_images("unicode")
    config = Config(path=tmp_path / "config.toml")
    created: list[Config] = []

    def factory(cfg: Config):
        created.append(cfg)
        return DemoBackend(tmp_path / "media")

    app = TelegaApp(config, backend_factory=factory)
    async with app.run_test(size=(120, 45)) as pilot:
        await _wait_for(pilot, ApiSetupScreen)
        assert not created  # без ключей бэкенд не создаётся

        await pilot.press(*"12x34", "enter")  # буквы в api_id не вводятся
        await pilot.press(*"abc", "enter")  # слишком короткий
        error = str(app.screen.query_one("#setup-error").render())
        assert "api_hash" in error
        assert isinstance(app.screen, ApiSetupScreen)

        await pilot.press("backspace", "backspace", "backspace", *HASH, "enter")
        await _wait_for(pilot, MainScreen)

    assert created and created[0].telegram.api_id == 1234
    data = tomllib.loads(config.path.read_text())
    assert data["telegram"] == {"api_id": 1234, "api_hash": HASH}


async def test_setup_skipped_when_credentials_known(tmp_path):
    init_images("unicode")
    config = Config(path=tmp_path / "config.toml")
    config.telegram.api_id, config.telegram.api_hash = 1, HASH
    app = TelegaApp(config, backend_factory=lambda cfg: DemoBackend(tmp_path / "media"))
    async with app.run_test(size=(120, 45)) as pilot:
        await _wait_for(pilot, MainScreen)


async def test_rejected_credentials_return_to_setup(tmp_path):
    init_images("unicode")
    config = Config(path=tmp_path / "config.toml")
    config.telegram.api_id, config.telegram.api_hash = 1, HASH
    app = TelegaApp(config, backend_factory=lambda cfg: RejectingBackend(tmp_path / "media"))
    async with app.run_test(size=(120, 45)) as pilot:
        await _wait_for(pilot, LoginScreen)
        await pilot.press(*"+79001234567", "enter")
        setup = await _wait_for(pilot, ApiSetupScreen)
        assert "не принял" in str(setup.query_one("#setup-error").render())
        # поля заполнены прежними значениями — можно поправить опечатку
        assert setup.query_one("#api-id").value == "1"


class HangingBackend(DemoBackend):
    """Первое подключение зависает, второе проходит; отправка кода зависает."""

    connects = 0

    async def connect(self) -> None:
        HangingBackend.connects += 1
        if HangingBackend.connects == 1:
            await asyncio.sleep(3600)
        await super().connect()

    async def is_authorized(self) -> bool:
        return False

    async def send_code(self, phone: str) -> None:
        await asyncio.sleep(3600)


async def test_connect_timeout_then_retry(tmp_path, monkeypatch):
    import telega.ui.app as app_module
    import telega.ui.screens.login as login_module

    init_images("unicode")
    monkeypatch.setattr(app_module, "CONNECT_TIMEOUT", 0.3)
    monkeypatch.setattr(login_module, "STEP_TIMEOUT", 0.3)
    HangingBackend.connects = 0
    config = Config(path=tmp_path / "config.toml")
    config.telegram.api_id, config.telegram.api_hash = 1, HASH
    app = TelegaApp(config, backend_factory=lambda cfg: HangingBackend(tmp_path / "media"))
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause(0.6)
        splash = str(app.query_one("#splash").render())
        assert "не ответил" in splash and "r — повторить" in splash
        await pilot.press("r")
        login = await _wait_for(pilot, LoginScreen)
        assert HangingBackend.connects == 2
        # зависший шаг входа не блокирует экран навсегда
        await pilot.press(*"+79001234567", "enter")
        await pilot.pause(0.6)
        assert "не ответил" in str(login.query_one("#login-error").render())
        assert not login.query_one("#login-input").disabled


async def test_eager_task_factory_is_disabled(tmp_path):
    """Регрессия: Textual в App.run() включает eager-фабрику задач, с которой
    Telethon зависает при подключении. Приложение должно её выключать."""
    init_images("unicode")
    loop = asyncio.get_running_loop()
    loop.set_task_factory(asyncio.eager_task_factory)  # как делает App.run()
    try:
        app = TelegaApp(Config(path=tmp_path / "config.toml"), DemoBackend(tmp_path / "media"))
        async with app.run_test(size=(120, 45)) as pilot:
            await _wait_for(pilot, MainScreen)
            assert loop.get_task_factory() is None
    finally:
        loop.set_task_factory(None)
