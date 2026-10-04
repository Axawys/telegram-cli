#!/bin/sh
# Установка и обновление telega-cli одной командой:
#
#   curl -fsSL https://raw.githubusercontent.com/Axawys/telegram-cli/main/install.sh | sh
#
# Что делает:
#   1. проверяет Python 3.12+;
#   2. ставит pipx, если его нет (pacman / apt / dnf / zypper / brew);
#   3. ставит telega-cli в отдельное окружение pipx (повторный запуск — обновление);
#   4. добавляет каталог pipx (~/.local/bin) в PATH, если его там нет.
#
# Переменные и аргументы:
#   TELEGA_REF=<ветка|тег>   что ставить с GitHub (по умолчанию main);
#   sh install.sh <путь|URL> поставить из локального клона или другого источника.
# Удаление: pipx uninstall telega-cli

set -eu

REPO="https://github.com/Axawys/telegram-cli"
REF="${TELEGA_REF:-main}"
# Архив вместо git+https: так не нужен git.
SOURCE="${1:-$REPO/archive/refs/heads/$REF.zip}"
case "$REF" in v[0-9]*) SOURCE="${1:-$REPO/archive/refs/tags/$REF.zip}" ;; esac
PACKAGE="telega-cli"

if [ -t 1 ]; then B='\033[1;34m' Y='\033[1;33m' R='\033[1;31m' N='\033[0m'; else B='' Y='' R='' N=''; fi
say() { printf "${B}==>${N} %s\n" "$*"; }
warn() { printf "${Y}!!${N} %s\n" "$*" >&2; }
die() { printf "${R}Ошибка:${N} %s\n" "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"; elif have sudo; then sudo "$@"; else
        die "нужны права root для: $*"; fi
}

# --- Python ----------------------------------------------------------------

PYTHON=""
for candidate in python3 python3.14 python3.13 python3.12 python; do
    if have "$candidate" && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
        PYTHON="$(command -v "$candidate")"
        break
    fi
done
[ -n "$PYTHON" ] || die "нужен Python 3.12 или новее (python3 --version). Установите его пакетным менеджером."
say "Python: $("$PYTHON" --version 2>&1) ($PYTHON)"

# --- pipx ------------------------------------------------------------------

install_pipx() {
    say "pipx не найден, ставлю…"
    if have pacman; then as_root pacman -S --needed --noconfirm python-pipx
    elif have apt-get; then as_root apt-get update -q && as_root apt-get install -y pipx
    elif have dnf; then as_root dnf install -y pipx
    elif have zypper; then as_root zypper --non-interactive install python3-pipx
    elif have brew; then brew install pipx
    else "$PYTHON" -m pip install --user pipx || die "не удалось поставить pipx, поставьте его вручную: https://pipx.pypa.io"
    fi
}

if have pipx; then PIPX="pipx"
elif "$PYTHON" -m pipx --version >/dev/null 2>&1; then PIPX="$PYTHON -m pipx"
else
    install_pipx
    if have pipx; then PIPX="pipx"; else PIPX="$PYTHON -m pipx"; fi
fi

# --- telega-cli --------------------------------------------------------------

if $PIPX list --short 2>/dev/null | grep -q "^$PACKAGE "; then
    say "Обновляю $PACKAGE из $SOURCE"
else
    say "Ставлю $PACKAGE из $SOURCE"
fi
# --force пересоздаёт окружение: так повторный запуск всегда обновляет,
# даже если номер версии не поменялся.
$PIPX install --force --python "$PYTHON" "$SOURCE"

# --- PATH --------------------------------------------------------------------

BIN_DIR="$($PIPX environment --value PIPX_BIN_DIR 2>/dev/null || echo "$HOME/.local/bin")"
case ":$PATH:" in
    *":$BIN_DIR:"*) ON_PATH=1 ;;
    *) ON_PATH=0 ;;
esac
if [ "$ON_PATH" -eq 0 ]; then
    $PIPX ensurepath >/dev/null 2>&1 || warn "добавьте $BIN_DIR в PATH вручную"
fi

echo
say "Готово: $("$BIN_DIR/telega" --version 2>/dev/null || echo "$PACKAGE")"
if [ "$ON_PATH" -eq 1 ]; then
    echo "    Запуск:      telega          (демо без аккаунта: telega --demo)"
else
    echo "    $BIN_DIR добавлен в PATH — откройте новый терминал и запустите: telega"
    echo "    Или прямо сейчас: $BIN_DIR/telega"
fi
echo "    Обновление:  запустите эту же команду установки ещё раз"
echo "    Удаление:    pipx uninstall $PACKAGE"
