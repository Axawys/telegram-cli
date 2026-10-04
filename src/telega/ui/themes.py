"""Цветовые темы (выбор — Space t, :theme, [ui].theme в config.toml).

Каждая тема — это Theme Textual (переменные $accent, $panel …) плюс ANSI-палитра.
Палитра нужна потому, что render.py и виджеты красят текст именованными
цветами Rich («cyan», «bold yellow»), а Textual переводит их в RGB по
`ansi_theme_dark` / `ansi_theme_light`. Без своей палитры, например, жёлтый
бейдж «@» остался бы нечитаемым на светлом фоне.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.terminal_theme import TerminalTheme
from textual.app import App
from textual.theme import Theme

from telega.config import THEMES


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _ansi(bg: str, fg: str, normal: list[str], bright: list[str]) -> TerminalTheme:
    """normal/bright — black, red, green, yellow, blue, magenta, cyan, white."""
    return TerminalTheme(_hex(bg), _hex(fg), [_hex(c) for c in normal], [_hex(c) for c in bright])


@dataclass(frozen=True)
class ThemeSpec:
    title: str
    theme: Theme
    ansi: TerminalTheme

    @property
    def dark(self) -> bool:
        return self.theme.dark


def _spec(name: str, title: str, *, dark: bool, bg: str, surface: str, panel: str, fg: str,
          primary: str, secondary: str, accent: str, warning: str, error: str, success: str,
          normal: list[str], bright: list[str]) -> ThemeSpec:
    theme = Theme(
        name=f"telega-{name}",
        dark=dark,
        primary=primary,
        secondary=secondary,
        accent=accent,
        warning=warning,
        error=error,
        success=success,
        foreground=fg,
        background=bg,
        surface=surface,
        panel=panel,
    )
    return ThemeSpec(title, theme, _ansi(bg, fg, normal, bright))


SPECS: dict[str, ThemeSpec] = {
    "cold": _spec(
        "cold", "Холодная (тёмная)", dark=True,
        bg="#1a1d26", surface="#222633", panel="#2b3142", fg="#c8d3e6",
        primary="#7aa2f7", secondary="#7dcfff", accent="#7dcfff",
        warning="#e0af68", error="#f7768e", success="#9ece6a",
        normal=["#2b3142", "#f7768e", "#9ece6a", "#e0af68", "#7aa2f7", "#bb9af7", "#7dcfff", "#a9b1d6"],
        bright=["#565f89", "#ff8fa3", "#b9f27c", "#ffc777", "#8fb0ff", "#c9a8ff", "#a4e6ff", "#d5dcf0"],
    ),
    "warm": _spec(
        "warm", "Тёплая (тёмная)", dark=True,
        bg="#1f1b16", surface="#2a241d", panel="#3a3128", fg="#ebdbb2",
        primary="#d65d0e", secondary="#d79921", accent="#fe8019",
        warning="#fabd2f", error="#fb4934", success="#b8bb26",
        normal=["#3a3128", "#fb4934", "#b8bb26", "#fabd2f", "#83a598", "#d3869b", "#8ec07c", "#d5c4a1"],
        bright=["#7c6f64", "#ff6f5e", "#d0d33a", "#ffd25a", "#9fc1b4", "#e6a0b4", "#a8d896", "#fbf1c7"],
    ),
    "vivid": _spec(
        "vivid", "Насыщенная (тёмная)", dark=True,
        bg="#0d0b14", surface="#16121f", panel="#221a30", fg="#f0e9ff",
        primary="#ff2e97", secondary="#00e5ff", accent="#b026ff",
        warning="#ffd400", error="#ff3355", success="#00ff9c",
        normal=["#221a30", "#ff3355", "#00ff9c", "#ffd400", "#3d7bff", "#ff2e97", "#00e5ff", "#d8ccf0"],
        bright=["#5a4a78", "#ff6680", "#5cffbe", "#ffe45c", "#6e9bff", "#ff66b3", "#5cf0ff", "#ffffff"],
    ),
    "pastel": _spec(
        "pastel", "Пастельная (тёмная)", dark=True,
        bg="#1e1e2e", surface="#262637", panel="#313244", fg="#cdd6f4",
        primary="#cba6f7", secondary="#f5c2e7", accent="#b4befe",
        warning="#f9e2af", error="#f38ba8", success="#a6e3a1",
        normal=["#313244", "#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#f5c2e7", "#94e2d5", "#bac2de"],
        bright=["#585b70", "#f5a3b9", "#bbebb7", "#fbeac4", "#a5c6fb", "#f8d3ee", "#afe9df", "#e0e6fa"],
    ),
    # Matte Black из Omarchy: цвета из ~/.local/state/omarchy/current/theme/
    # (colors.toml, kitty.conf). ANSI-палитра — как у терминала в этой теме,
    # поэтому «зелёный» там янтарный, а «голубой» серый.
    "matte": _spec(
        "matte", "Матовая чёрная (Omarchy)", dark=True,
        bg="#121212", surface="#1e1e1e", panel="#2a2a2a", fg="#bebebe",
        primary="#e68e0d", secondary="#f59e0b", accent="#e68e0d",
        warning="#ffc107", error="#d35f5f", success="#ffc107",
        normal=["#121212", "#d35f5f", "#ffc107", "#b91c1c", "#e68e0d", "#d35f5f", "#bebebe", "#bebebe"],
        bright=["#333333", "#b91c1c", "#ffc107", "#b90a0a", "#f59e0b", "#b91c1c", "#eaeaea", "#bebebe"],
    ),
    "light": _spec(
        "light", "Светлая", dark=False,
        bg="#f5f5f7", surface="#ffffff", panel="#e4e6eb", fg="#24292f",
        primary="#0969da", secondary="#8250df", accent="#0969da",
        warning="#9a6700", error="#cf222e", success="#1a7f37",
        normal=["#24292f", "#cf222e", "#116329", "#7d4e00", "#0969da", "#8250df", "#1b7c83", "#6e7781"],
        bright=["#57606a", "#a40e26", "#1a7f37", "#633c01", "#218bff", "#a475f9", "#3192aa", "#8c959f"],
    ),
    "bright": _spec(
        "bright", "Яркая (светлая)", dark=False,
        bg="#fffdf7", surface="#ffffff", panel="#ffe9c7", fg="#1a1a2e",
        primary="#ff4f00", secondary="#0077ff", accent="#e6007e",
        warning="#e08b00", error="#e60026", success="#00a651",
        normal=["#1a1a2e", "#e60026", "#009944", "#c77700", "#0055ff", "#d4007a", "#008c99", "#8a8aa0"],
        bright=["#4a4a68", "#ff1f4b", "#00b856", "#e08b00", "#2e7bff", "#ff1a9c", "#00a8b8", "#b0b0c4"],
    ),
}

assert tuple(SPECS) == THEMES, "список тем в config.THEMES и здесь должен совпадать"


def register_themes(app: App) -> None:
    for spec in SPECS.values():
        app.register_theme(spec.theme)


def apply_theme(app: App, name: str) -> None:
    """Включить тему вместе с её ANSI-палитрой."""
    spec = SPECS[name]
    # Палитру ставим до смены темы: смена темы перерисует всё с новой палитрой.
    if spec.dark:
        app.ansi_theme_dark = spec.ansi
    else:
        app.ansi_theme_light = spec.ansi
    app.theme = spec.theme.name
