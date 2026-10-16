"""Первый запуск: ввод api_id / api_hash в терминале."""

from __future__ import annotations

import asyncio
import tomllib

import pytest

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


class LoginBackend(DemoBackend):
    """Не авторизован: проходим вход как с настоящим аккаунтом."""

    async def is_authorized(self) -> bool:
        return False


async def test_login_shows_where_code_went_and_resends(tmp_path):
    from textual.widgets import Static

    init_images("unicode")
    app = TelegaApp(Config(path=tmp_path / "c.toml"), LoginBackend(tmp_path / "media"))
    async with app.run_test(size=(100, 30)) as pilot:
        login = await _wait_for(pilot, LoginScreen)
        await pilot.press(*"+79001234567", "enter")
        await pilot.pause(0.2)
        assert login.step == "code"
        text = str(login.query_one("#login-delivery", Static).render())
        assert "Код отправлен в демо-режиме" in text and "(5 цифр)" in text
        assert "Ctrl+R — прислать по SMS" in text

        await pilot.press("ctrl+r")  # прислать иначе
        await pilot.pause(0.2)
        assert "Код отправлен по SMS" in str(login.query_one("#login-delivery", Static).render())

        await pilot.press("escape")  # назад к номеру
        assert login.step == "phone"
        assert "Ctrl+L — войти по QR-коду" in str(login.query_one("#login-delivery", Static).render())


def test_code_delivery_descriptions():
    from telethon.tl import types

    from telega.backend.telethon_backend import TelethonBackend, _describe_code
    from telega.models import BackendError

    def sent(code_type, next_type=None, timeout=None):
        return types.auth.SentCode(code_type, "hash", next_type=next_type, timeout=timeout)

    app = _describe_code(sent(types.auth.SentCodeTypeApp(5), types.auth.CodeTypeSms(), 60))
    assert "приложение Telegram" in app.where and "не SMS" in app.where
    assert (app.length, app.next_way, app.resend_after) == (5, "по SMS", 60)
    mail = _describe_code(sent(types.auth.SentCodeTypeEmailCode("a***@gmail.com", 6)))
    assert "a***@gmail.com" in mail.where and mail.next_way is None
    assert "звонком" in _describe_code(sent(types.auth.SentCodeTypeCall(5))).where
    with pytest.raises(BackendError, match="почту для входа"):
        _describe_code(sent(types.auth.SentCodeTypeSetUpEmailRequired()))

    backend = TelethonBackend.__new__(TelethonBackend)  # без сети
    paid = types.auth.SentCodePaymentRequired("p", "hash", "s@t.org", "subj", 7, "USD", 100)
    with pytest.raises(BackendError, match="оплату"):
        backend._code_sent(paid)
    backend._code_sent(sent(types.auth.SentCodeTypeSms(5)))
    assert backend._code_hash == "hash"  # хэш запомнен для sign_in


def test_qr_text_matches_matrix():
    import segno
    from rich.console import Console

    from telega.ui.qr import qr_text

    console = Console()

    url = "tg://login?token=AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA"
    matrix = [list(r) for r in segno.make(url, error="l").matrix_iter(border=2)]
    text = qr_text(url)
    # Восстановить модули из цветов «▀» (верх — цвет текста, низ — фон).
    rows: list[list[int]] = []
    for line in text.split("\n"):
        top, bottom = [], []
        for span_char in range(len(line.plain)):
            style = line.get_style_at_offset(console, span_char)
            top.append(int(style.color.triplet.red == 0))
            bottom.append(int(style.bgcolor.triplet.red == 0))
        rows += [top, bottom]
    assert rows[: len(matrix)] == matrix


async def test_login_by_qr(tmp_path):
    from textual.widgets import Static

    init_images("unicode")
    backend = LoginBackend(tmp_path / "media")
    backend.qr_lifetime = 0.3  # токен быстро истекает — QR должен обновиться
    urls = []
    original = backend.qr_login_url

    async def counting_url():
        urls.append(await original())
        return urls[-1]

    backend.qr_login_url = counting_url
    app = TelegaApp(Config(path=tmp_path / "c.toml"), backend)
    async with app.run_test(size=(100, 40)) as pilot:
        login = await _wait_for(pilot, LoginScreen)
        assert "Ctrl+L" in str(login.query_one("#login-delivery", Static).render())
        await pilot.press("ctrl+l")
        await pilot.pause(0.8)
        assert login.step == "qr" and len(urls) >= 2  # истёк — получили новый
        qr = login.query_one("#login-qr", Static)
        assert qr.display and "▀" in str(qr.render())
        assert not login.query_one("#login-input").display

        await pilot.press("escape")  # назад к номеру — ожидание QR остановлено
        assert login.step == "phone" and not qr.display

        backend.qr_lifetime = 30
        await pilot.press("ctrl+l")
        await pilot.pause(0.1)
        backend.scan_qr()  # «отсканировали телефоном»
        await _wait_for(pilot, MainScreen)


async def test_login_by_qr_with_password(tmp_path):
    init_images("unicode")
    backend = LoginBackend(tmp_path / "media")
    backend.qr_needs_password = True
    app = TelegaApp(Config(path=tmp_path / "c.toml"), backend)
    async with app.run_test(size=(100, 40)) as pilot:
        login = await _wait_for(pilot, LoginScreen)
        await pilot.press("ctrl+l")
        await pilot.pause(0.1)
        backend.scan_qr()
        await pilot.pause(0.2)
        assert login.step == "password" and login.query_one("#login-input").display
        await pilot.press(*"secret", "enter")
        await _wait_for(pilot, MainScreen)
