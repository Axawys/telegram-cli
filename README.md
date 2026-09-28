# telegram-cli

**English** · [Русский](README.ru.md)

A terminal Telegram client with vim-like controls and images right in your terminal. The command is `telega`.

> Unofficial client. This project is not affiliated with or endorsed by Telegram. It uses the official [Telegram API](https://core.telegram.org/api) with your own `api_id` / `api_hash`.

- **vim controls**: NORMAL / INSERT / COMMAND modes, counts (`5j`), key sequences (`gg`, `dd`, `yy`), `:commands`, `/search`.
- **Images**: photos in messages and channel posts, a large avatar in profiles. kitty uses the Terminal Graphics Protocol, foot uses Sixel. The protocol is detected automatically.
- **GIFs and stickers** (prototype): animated (`.tgs`), video (`.webm` with transparency) and static (`.webp`). The selected message animates; `o` opens it fullscreen.
- **Mentions**: highlighting of @mentions, #hashtags and links, autocompletion of chat members when you type `@`, proper mentions of users without a username.
- Replies, editing, deleting, copying, profiles, chat filter, message search, a hideable chat list.
- **Demo mode** (`--demo`) that needs no account or network.

Stack: Python 3.12+, [Telethon](https://github.com/LonamiWebs/Telethon) (MTProto), [Textual](https://textual.textualize.io/) (TUI), [textual-image](https://github.com/lnqs/textual-image) (kitty / sixel), [PyAV](https://github.com/PyAV-Org/PyAV) and [rlottie-python](https://github.com/laggykiller/rlottie-python) (animations).

## Installation

You need Python 3.12 or newer. Everything else is installed by pip; ffmpeg comes bundled with PyAV.

```bash
git clone https://github.com/Axawys/telegram-cli.git
cd telegram-cli
python3 -m venv .venv
.venv/bin/pip install -e .
```

Run it with `.venv/bin/telega`. To make `telega` available everywhere:

```bash
ln -s "$PWD/.venv/bin/telega" ~/.local/bin/telega
```

## First run

Start `telega`. If no API keys are configured yet, a setup screen opens:

1. It has step-by-step instructions for getting an `api_id` and `api_hash` at <https://my.telegram.org/apps>. `Ctrl+O` opens the site in your browser.
2. Paste both values. `Enter` moves to the next field and saves on the last one.
3. The keys are saved to `~/.config/telega-cli/config.toml` with `600` permissions.
4. Then enter your phone number, the code Telegram sends you and, if two-step verification is on, your password.

If Telegram rejects the keys, the setup screen opens again. `Ctrl+E` on the login screen also returns to it, and `telega --setup` restarts setup. You can also set the keys with the `TELEGA_API_ID` / `TELEGA_API_HASH` environment variables.

If my.telegram.org shows "ERROR" when you create the app, fill in every field using Latin characters, turn off VPNs and ad blockers, log in to the site again, or try later.

The session is stored in `~/.local/share/telega-cli/telega.session`. **This file gives full access to your account.** Never share it.

To look at the interface without an account: `telega --demo`.

## Controls (short)

| Keys | Action |
|---|---|
| `j` / `k`, `gg` / `G`, `C-d` / `C-u` | navigation, with counts: `5j` |
| `Enter` / `l` | open chat |
| `h`, `Tab` | go to the chat list / switch pane |
| `C-n`, `:sidebar` | hide / show the chat list |
| `i` / `a` | write a message (INSERT), `Esc` to go back |
| `r` / `e` / `dd` / `yy` | reply / edit / delete / copy |
| `K` | profile (of the chat or the message author) with avatar |
| `o` / `Enter` on media | image or animation fullscreen |
| `/` | filter chats or search messages, `n` / `N` |
| `:open name`, `:profile`, `:q` | commands |
| `?` | help |

In INSERT mode, `@` plus letters opens member suggestions: `Tab` / `C-n` / `C-p` cycle through them and `Enter` picks one. `Enter` sends; `Shift+Enter` / `Alt+Enter` / `C-j` insert a newline.

Full list (in Russian): [docs/KEYBINDINGS.md](docs/KEYBINDINGS.md).

## Images and animations

| Terminal | Protocol | Animation |
|---|---|---|
| kitty, ghostty | `tgp` (kitty graphics protocol) | the terminal animates natively |
| foot, wezterm, konsole, xterm | `sixel` | frames swapped by the app |
| others | `halfcell` (colored half blocks) | frames swapped by the app |

The default is `image_protocol = "auto"`. Override it once with `telega --images sixel`, or turn images off with `--images none`. In tmux you need `allow-passthrough on` and `terminal-features ',*:RGB:sixel'`.

Animation settings: `animations = "selected" | "fullscreen" | "off"` and `kitty_native_animation` (flag `--no-kitty-anim`). All options are described in [`config.example.toml`](config.example.toml).

## Files

| Path | Contents |
|---|---|
| `~/.config/telega-cli/config.toml` | configuration |
| `~/.local/share/telega-cli/telega.session` | Telegram session |
| `~/.cache/telega-cli/media/` | cache of images, animations and avatars (safe to delete) |
| `~/.local/state/telega-cli/telega.log` | log (`--debug` for verbose) |

## Development

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check src tests
```

Developer documentation is currently in Russian:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): layers and data flow.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): environment, tests, how to add features, debugging, pitfalls.
- [docs/KEYBINDINGS.md](docs/KEYBINDINGS.md): all keys and commands.
- [docs/ROADMAP.md](docs/ROADMAP.md): what is done, what is next, known limitations.

## License

[GNU GPL v3.0 or later](LICENSE). You are free to use, study, modify and share this program. Derivative works must be distributed under the same license, with source code.
