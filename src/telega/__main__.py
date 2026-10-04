"""Точка входа: `telega` или `python -m telega`."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from telega import __version__
from telega.config import IMAGE_PROTOCOLS, ConfigError, load_config


def _setup_logging(path: Path, debug: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=path,
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Telethon очень разговорчив на DEBUG
    logging.getLogger("telethon").setLevel(logging.INFO if debug else logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="telega", description="Терминальный клиент Telegram")
    parser.add_argument("--demo", action="store_true", help="демо-режим без сети и аккаунта")
    parser.add_argument("--config", type=Path, help="путь к config.toml")
    parser.add_argument("--setup", action="store_true", help="заново ввести api_id / api_hash")
    parser.add_argument("--images", choices=IMAGE_PROTOCOLS, help="протокол картинок (перекрывает конфиг)")
    parser.add_argument(
        "--no-kitty-anim", action="store_true",
        help="в kitty менять кадры из приложения, а не встроенной анимацией терминала",
    )
    parser.add_argument("--debug", action="store_true", help="подробный лог")
    parser.add_argument("--version", action="version", version=f"telega-cli {__version__}")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 2
    if args.images:
        config.ui.image_protocol = args.images
    if args.no_kitty_anim:
        config.ui.kitty_native_animation = False

    _setup_logging(config.log_path, args.debug)
    for warning in config.warnings:
        logging.getLogger("telega").warning("config: %s", warning)

    # Определение графики терминала — строго ДО запуска Textual.
    from telega.ui.widgets.image import init_images

    init_images(config.ui.image_protocol)

    from telega.ui.app import TelegaApp

    if args.demo:
        from telega.backend.demo import DemoBackend

        app = TelegaApp(config, DemoBackend(config.media_dir / "demo"))
    else:
        from telega.backend.telethon_backend import TelethonBackend

        # Бэкенд создаётся внутри приложения: если api_id/api_hash не заданы,
        # сначала покажется экран настройки.
        app = TelegaApp(config, backend_factory=TelethonBackend, force_setup=args.setup)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
