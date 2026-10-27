"""Server-rendered web dashboard for the pool (Jinja2 templates): install scripts + render_* HTML."""
import calendar
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

from flask import g, has_request_context
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from hashpass.registry import era, perms
from hashpass.registry.attempt_store import is_live
from hashpass.registry.codeview import highlight_lines, render_markdown_html
from hashpass.registry.progress_store import outside_course
from hashpass.registry.reference import normalise as _norm_cmd
from hashpass.version import TRUSTED_HOSTS

_REPO = "Bunnyton/hashpass"
_TEMPLATES = Path(__file__).parent / "templates"

# One module-level Jinja env so render_* stays a plain function (usable from tests without Flask).
_env = Environment(loader=FileSystemLoader(str(_TEMPLATES)),
                   autoescape=select_autoescape(("html", "j2", "html.j2")),
                   trim_blocks=False, lstrip_blocks=False)
# Who is looking (set by the server per request): the nav shows admin-only pages to the admin only.
_env.globals["viewer_is_admin"] = lambda: bool(getattr(g, "hp_admin", False)) if has_request_context() else False
# The viewer's time zone from their settings ("" = the browser's): static/time.js renders every
# <time class='ts'> in it.
_env.globals["viewer_tz"] = lambda: str(getattr(g, "hp_tz", "")) if has_request_context() else ""
# Staff pages (progress, the old catalog) in the nav: admins and authors; no request -> shown (tests).
_env.globals["viewer_is_staff"] = (lambda: bool(getattr(g, "hp_staff", True))
                                   if has_request_context() else True)
_env.globals["courses_on"] = era.courses_on
_env.globals["viewer_login"] = lambda: str(getattr(g, "hp_user", "") or "") if has_request_context() else ""


def safe_id(text: str) -> str:
    """Make an HTML id fragment from a session id (hex in practice; anything else is stripped)."""
    return re.sub(r"[^A-Za-z0-9_-]", "", text)[:64]


def _epoch(value: object) -> float | None:
    """Convert a stored moment -- epoch seconds or an ISO `YYYY-MM-DDTHH:MM:SSZ` -- to epoch seconds."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return float(calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")))
        except ValueError:
            return None
    return None


def ts_html(value: object) -> Markup | str:
    """
    One moment for a page: `<time class='ts' datetime=UTC>` with a UTC fallback text.

    The page shows it in the viewer's zone (settings, else the browser's) -- static/time.js
    rewrites the text; without JS the UTC time stays readable.
    """
    sec = _epoch(value)
    if sec is None:
        return "—"
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(sec))
    text = time.strftime("%d.%m.%Y %H:%M UTC", time.gmtime(sec))
    return Markup(f"<time class='ts' datetime='{iso}'>{text}</time>")  # noqa: S704  (no user text)


def ago_html(value: object) -> Markup | str:
    """
    One moment told the GitHub way, «2 дня назад» (static/time.js), the full date in its tooltip.

    Without JS the date stays, as `ts` writes it.
    """
    sec = _epoch(value)
    if sec is None:
        return "—"
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(sec))
    text = time.strftime("%d.%m.%Y %H:%M UTC", time.gmtime(sec))
    return Markup(f"<time class='ts' data-rel datetime='{iso}'>{text}</time>")  # noqa: S704  (no user text)


_env.globals["ts"] = ts_html
_env.globals["ago"] = ago_html
_env.globals["has_avatar"] = lambda _login: False   # search_web sets the real one
_env.filters["q"] = lambda v: quote(str(v), safe="")
_env.filters["ref_url"] = lambda v: quote(str(v), safe="/:")
_VERSION_REF = re.compile(r"^(?P<base>.+:.+)_v(?P<n>[1-9][0-9]*)$")


def version_ref(ref: object) -> Markup:
    """
    Show `repo:tag_vN` as `repo:tag` + «версия N» (user 2026-10-22: «не ревизия, а версия»).

    The `_vN` tag stays under the hood (URLs, API); people see a version beside the tag.
    """
    m = _VERSION_REF.match(str(ref))
    if m is None:
        return Markup.escape(str(ref))
    return Markup("{} <span class='pill sm ver'>версия {}</span>").format(m["base"], m["n"])


_env.filters["ver"] = version_ref


def plural(n: object, one: str, few: str, many: str) -> str:
    """Return «N word» with the Russian plural form: 1 курс, 3 курса, 5 курсов."""
    k = int(n or 0)
    tail = k % 100
    word = many if 11 <= tail <= 14 else {1: one, 2: few, 3: few, 4: few}.get(k % 10, many)  # noqa: PLR2004
    return f"{k} {word}"


_env.filters["plural"] = plural


def taking(n: object) -> str:
    """«проходит курс» / «проходят курс» after a count (user 2026-10-23: not «студенты»)."""
    k = int(n or 0)
    return "проходит курс" if k % 10 == 1 and k % 100 != 11 else "проходят курс"  # noqa: PLR2004


_env.filters["taking"] = taking


_INSTALL_TEMPLATE = """\
#!/usr/bin/env bash
# hashpass __ROLE__ installer -- served by the pool at __POOL__
set -euo pipefail
POOL="__POOL__"
echo "Установка hashpass; пул: $POOL"
if [ "$(uname -s)" = Darwin ]; then
  echo "hashpass работает в Linux: задания -- это контейнеры systemd-nspawn." >&2
  echo "На Mac поставьте Linux-виртуалку (например, Ubuntu в UTM) и запустите эту команду в ней." >&2
  exit 1
fi
# As root everything lands in ~root (~/.local, ~/.hashpass) and the student's own `hashpass`
# finds nothing, or a root-owned home it cannot write (user 2026-10-25: «ломает много что»).
if [ "$(id -u)" = 0 ]; then
  echo "Не запускайте установку от root или через sudo: hashpass ставится в домашний каталог" >&2
  echo "пользователя, который будет решать задания. Войдите им и повторите команду без sudo." >&2
  exit 1
fi
# sudo/apt read the password and answers from the terminal, not from the `curl |` pipe; with no
# controlling terminal (ssh without -t, su -, CI) /dev/tty does not open -> /dev/null instead.
TTY=/dev/tty; ( : </dev/tty ) 2>/dev/null || TTY=/dev/null
# Preflight: everything the install needs must be present BEFORE we download anything.
# Package names and the install command follow the host's package manager (Debian/Ubuntu,
# Arch, Fedora); the task containers are Debian regardless of the host.
if command -v pacman >/dev/null 2>&1; then
  # -Syu, not -Sy + -S: a partial upgrade is unsupported on Arch
  PKG_REFRESH=":"; PKG_INSTALL="sudo pacman -Syu --needed --noconfirm"
  P_PY=python; P_PIP=python-pip; P_NSPAWN=systemd
  P_QEMU="qemu-user-static qemu-user-static-binfmt"
elif command -v dnf >/dev/null 2>&1; then
  PKG_REFRESH=":"; PKG_INSTALL="sudo dnf install -y"
  P_PY=python3; P_PIP=python3-pip; P_NSPAWN=systemd-container
  P_QEMU="qemu-user-static-x86"
else
  # A fresh Debian/Ubuntu has stale package lists -> «Unable to locate package» without an update.
  # noninteractive: tzdata/needrestart must not stop the install with a dialog
  PKG_REFRESH="sudo apt update"; PKG_INSTALL="sudo env DEBIAN_FRONTEND=noninteractive apt install -y"
  P_PY=python3; P_PIP=python3-pip; P_NSPAWN=systemd-container
  P_QEMU="qemu-user-static binfmt-support"
fi
missing=""
command -v python3 >/dev/null 2>&1 || missing="$missing $P_PY"
python3 -m pip --version >/dev/null 2>&1 || missing="$missing $P_PIP"
command -v git >/dev/null 2>&1 || missing="$missing git"
command -v curl >/dev/null 2>&1 || missing="$missing curl"
# the task consoles are systemd-nspawn machines driven by machinectl (both in systemd-container)
if ! command -v systemd-nspawn >/dev/null 2>&1 || ! command -v machinectl >/dev/null 2>&1; then
  missing="$missing $P_NSPAWN"
fi
# The task images are x86_64 Debian. Another CPU (arm64: a Raspberry Pi, a Linux VM on a Mac)
# runs them through an x86 emulator registered in binfmt_misc: Rosetta (UTM / Apple
# Virtualization with «Enable Rosetta») when the VM has it, else qemu-user.
ARCH="$(uname -m)"
EMULATED=""
case "$ARCH" in
  x86_64|amd64) ;;
  *) EMULATED=1
     if [ ! -e /proc/sys/fs/binfmt_misc/rosetta ] && [ ! -e /proc/sys/fs/binfmt_misc/qemu-x86_64 ]; then
       echo "процессор $ARCH: задания x86_64 пойдут через эмулятор x86"
       missing="$missing $P_QEMU"
     fi ;;
esac
if [ -n "$missing" ]; then
  # Install them right here (sudo asks for the password on the terminal, so `curl | bash` works).
  echo "ставлю недостающие пакеты:$missing"
  $PKG_REFRESH <"$TTY" || true
  # shellcheck disable=SC2086  # word-splitting of the command and the package list is intended
  if ! $PKG_INSTALL$missing <"$TTY"; then
    echo "не удалось поставить:$missing" >&2
    echo "поставьте вручную и повторите:  $PKG_INSTALL$missing" >&2
    exit 1
  fi
fi
if [ -n "$EMULATED" ] && [ ! -e /proc/sys/fs/binfmt_misc/rosetta ] && [ ! -e /proc/sys/fs/binfmt_misc/qemu-x86_64 ]; then
  # a fresh qemu package registers itself at the next boot; register it now
  sudo systemctl restart systemd-binfmt <"$TTY" 2>/dev/null || sudo update-binfmts --enable qemu-x86_64 <"$TTY" 2>/dev/null || true
  [ -e /proc/sys/fs/binfmt_misc/qemu-x86_64 ] || echo "эмулятор x86 не включился -- перезагрузите машину и повторите" >&2
fi
# Many consoles on one machine (a server): each console's systemd takes ~4 of root's inotify
# instances, 128 by default -- the 31st console died «Too many open files». Raise it for good.
if [ "$(cat /proc/sys/fs/inotify/max_user_instances 2>/dev/null || echo 0)" -lt 8192 ]; then
  echo "поднимаю лимит inotify ядра: много консолей hashpass на одной машине"
  sudo sh -c 'printf "fs.inotify.max_user_instances = 8192\nfs.inotify.max_user_watches = 1048576\n" > /etc/sysctl.d/60-hashpass.conf && sysctl -q -p /etc/sysctl.d/60-hashpass.conf' <"$TTY" \
    || echo "не удалось поднять лимит inotify -- не больше ~30 консолей одновременно" >&2
fi
# A school network may intercept TLS with a self-signed cert: then git/pip refuse GitHub, and
# the second try skips verification for exactly the hosts the install talks to.
TRUSTED="__TRUSTED__"
# hashpass needs Python >= 3.13; Ubuntu 22.04/24.04 and Debian 12 ship older ones. Pick a new
# enough interpreter, else install one: Ubuntu -> deadsnakes PPA, Fedora -> dnf, anything else ->
# a standalone CPython via uv (no root). Every pip/site call below goes through "$PY".
py_ok() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 13))' >/dev/null 2>&1; }
PY=""
for c in python3 python3.14 python3.13; do
  if command -v "$c" >/dev/null 2>&1 && py_ok "$c"; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then
  echo "нужен Python 3.13 (в системе $(python3 --version 2>&1 || echo 'его нет')) -- ставлю"
  if command -v apt >/dev/null 2>&1 && grep -qiE '^(ID|ID_LIKE)=.*ubuntu' /etc/os-release; then
    sudo env DEBIAN_FRONTEND=noninteractive apt install -y software-properties-common <"$TTY" || true
    sudo add-apt-repository -y ppa:deadsnakes/ppa <"$TTY" || true
    sudo env DEBIAN_FRONTEND=noninteractive apt install -y python3.13 python3.13-venv <"$TTY" || true
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3.13 <"$TTY" || true
  fi
  if command -v python3.13 >/dev/null 2>&1 && py_ok python3.13; then
    PY="$(command -v python3.13)"
  else
    UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
    if [ ! -x "$UV" ]; then
      { curl -fsSL https://astral.sh/uv/install.sh || curl -kfsSL https://astral.sh/uv/install.sh; } \
        | env UV_NO_MODIFY_PATH=1 sh
    fi
    "$UV" python install 3.13
    PY="$("$UV" python find 3.13)"
  fi
fi
if [ -z "$PY" ] || ! py_ok "$PY"; then
  echo "не удалось поставить Python 3.13 -- поставьте его вручную и повторите" >&2
  exit 1
fi
echo "Python: $PY ($("$PY" --version))"
# deadsnakes/uv Pythons come without pip -- and on Ubuntu 22.04 python3.13 even sees the system
# pip 22.0 (built for 3.10), which dies on `import distutils`. A plain `ensurepip --user` calls
# that one «already satisfied» and installs nothing: `--upgrade` puts a pip of its own into ~/.local.
if ! "$PY" -m pip --version >/dev/null 2>&1; then
  "$PY" -m ensurepip --user --upgrade >/dev/null 2>&1 || true
  if ! "$PY" -m pip --version >/dev/null 2>&1; then
    GETPIP="$(mktemp)"
    curl -fsSL -o "$GETPIP" https://bootstrap.pypa.io/get-pip.py \
      || curl -kfsSL -o "$GETPIP" https://bootstrap.pypa.io/get-pip.py
    "$PY" "$GETPIP" --user --break-system-packages \
      || PIP_TRUSTED_HOST="$TRUSTED" "$PY" "$GETPIP" --user --break-system-packages
    rm -f "$GETPIP"
  fi
  if ! "$PY" -m pip --version >/dev/null 2>&1; then
    echo "не удалось поставить pip для $PY -- поставьте его вручную ($PY -m ensurepip --user --upgrade) и повторите" >&2
    exit 1
  fi
fi
# Install ONE commit's tarball, not a `git+` URL: a git clone drags the whole history
# (hundreds of MB), the tarball is a few MB. The sha in the URL is also what the self-update
# compares against (version.installed_commit).
SHA="$(git ls-remote "https://github.com/__REPO__" refs/heads/main 2>/dev/null | cut -f1 || true)"
if [ -z "$SHA" ]; then
  SHA="$(git -c http.sslVerify=false ls-remote "https://github.com/__REPO__" refs/heads/main | cut -f1)"
fi
if [ -z "$SHA" ]; then
  echo "не удалось узнать версию hashpass на GitHub (нет сети?)" >&2
  exit 1
fi
# --break-system-packages is needed on PEP 668 distros (Debian 12+, Ubuntu 23.04+) but an
# older pip (Ubuntu 22.04: pip 22.0) rejects the unknown flag -- pass it only when supported.
BSP=""
"$PY" -m pip install --help 2>/dev/null | grep -q -- --break-system-packages && BSP="--break-system-packages"
pip_install() {   # pip_install ARGS... -- retry trusting the hosts above on a TLS failure
  # shellcheck disable=SC2086  # $BSP is empty or one flag
  "$PY" -m pip install --user $BSP "$@" && return 0
  echo "повторяю без проверки сертификата (самоподписанный прокси в сети?)" >&2
  # shellcheck disable=SC2086
  PIP_TRUSTED_HOST="$TRUSTED" "$PY" -m pip install --user $BSP "$@"
}
# `--upgrade --force-reinstall --no-deps`: pip normally sees "hashpass X.Y.Z is
# already installed" and does nothing -- even when `main` has moved and we forgot to
# bump the version.  --force-reinstall reinstalls the package no matter what;
# --no-deps avoids touching flask/textual/etc. (installed by the next line).
pip_install --upgrade --force-reinstall --no-deps \
    "https://github.com/__REPO__/archive/$SHA.tar.gz"
# `--ignore-installed`: deadsnakes' python3.13 sees /usr/lib/python3/dist-packages, and pip took
# apt's typing_extensions 4.10 (Ubuntu 24.04) as installed -- it dies on 3.13, so did textual.
# Every dependency goes into ~/.local, which comes first on sys.path.
pip_install --upgrade --ignore-installed "flask>=3.0" "textual>=1.0"
# `pip --user` puts the commands into ~/.local/bin. Ubuntu's ~/.profile adds that dir to PATH
# only if it ALREADY existed at login, Arch never does -- so `hashpass` was «command not found».
# Persist it for bash (~/.bashrc + ~/.profile), zsh (~/.zshrc) and fish (conf.d), idempotently,
# and say how to pick it up in the terminal that is already open.
BIN="$("$PY" -m site --user-base)/bin"
USER_SHELL="$(basename "${SHELL:-bash}")"
PATH_LINE='case ":$PATH:" in *":'"$BIN"':"*) ;; *) export PATH="'"$BIN"':$PATH" ;; esac  # hashpass'
add_line() {   # add_line FILE LINE -- append LINE once
  mkdir -p "$(dirname "$1")"
  grep -qsF "$2" "$1" || printf '\\n%s\\n' "$2" >> "$1"
}
add_line "$HOME/.bashrc" "$PATH_LINE"
add_line "$HOME/.profile" "$PATH_LINE"
if [ "$USER_SHELL" = zsh ] || [ -f "$HOME/.zshrc" ]; then
  add_line "$HOME/.zshrc" "$PATH_LINE"
fi
FISH_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/hashpass.fish"
if [ "$USER_SHELL" = fish ] || command -v fish >/dev/null 2>&1; then
  add_line "$FISH_CONF" "contains -- '$BIN' \\$PATH; or set -gx PATH '$BIN' \\$PATH  # hashpass"
fi
case "$USER_SHELL" in
  zsh)  RC_HINT="source ~/.zshrc" ;;
  fish) RC_HINT="source $FISH_CONF" ;;
  *)    RC_HINT="source ~/.bashrc" ;;
esac
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "Команды установлены в $BIN; этот каталог добавлен в PATH."
     echo "В уже открытом терминале выполните:  $RC_HINT   (или откройте новый терминал)" ;;
esac
mkdir -p "$HOME/.hashpass"
printf '{"url": "%s", "user": ""}\\n' "$POOL" > "$HOME/.hashpass/pool.json"
__EXTRA__
echo "Готово. __NEXT__"
"""

def _install_script(pool_url: str, *, role: str, nxt: str, extra: str = ":") -> str:
    return (_INSTALL_TEMPLATE
            .replace("__POOL__", pool_url.rstrip("/"))
            .replace("__REPO__", _REPO)
            .replace("__TRUSTED__", " ".join(TRUSTED_HOSTS))
            .replace("__ROLE__", role)
            .replace("__EXTRA__", extra)
            .replace("__NEXT__", nxt))


# `curl …/install.sh | bash -s -- <course link>`: the course is added right after the install
_COURSE_ON_INSTALL = """\
COURSE="${1:-}"
if [ -n "$COURSE" ]; then
  "$BIN/hashpass" --no-update add "$COURSE" <"$TTY" || echo "курс не добавлен — позже: hashpass add $COURSE"
fi"""


def render_install_script(pool_url: str) -> str:
    """Return the student install script (installs `hashpass`, seeds the pool URL; adds a course given as $1)."""
    return _install_script(pool_url, role="student", extra=_COURSE_ON_INSTALL,
                           nxt="Запустите:  hashpass   (без sudo — пароль sudo он спросит сам)")


def render_engine_install_script(pool_url: str) -> str:
    """Return the installer the old author link serves: the one installer (user 2026-10-23)."""
    return render_install_script(pool_url)


_PW_HINT = "Не короче 8 символов, минимум одна буква, одна цифра и один спецсимвол."


def render_front(pool_url: str) -> str:
    """Public front page: what the pool is + the one install command."""
    url = pool_url.rstrip("/")
    # A self-signed HTTPS pool needs curl -k to fetch the installer (the pip step uses GitHub's
    # real cert, so it is unaffected); a plain-http pool does not.
    flags = "-fsSLk" if pool_url.startswith("https://") else "-fsSL"
    return _env.get_template("front.html.j2").render(
        title="hashpass", nav=False, active="", url=url, flags=flags)


def render_login(error: str = "", *, signed_in: str = "", role: str = "", next_url: str = "",
                 courses: bool = False) -> str:
    """Login form; `signed_in` -- who is already in (sent here by an admin-only page)."""
    return _env.get_template("login.html.j2").render(
        title="Вход — hashpass", nav=False, active="", error=error, next=next_url, courses=courses,
        signed_in=signed_in, role={"author": "автор", "admin": "администратор"}.get(role, role))


def render_password_form(error: str = "", *, done: bool = False) -> str:
    """Change-own-password form alone (the settings page without the time-zone card)."""
    return render_settings(tz="", zones=[], error=error, done="Пароль изменён." if done else "")


def render_reset_form(token: str, error: str = "") -> str:
    """Set-a-new-password form reached via an admin-issued reset link (no login needed)."""
    return _env.get_template("reset.html.j2").render(
        title="Восстановление — hashpass", nav=False, active="",
        token=token, error=error, hint=_PW_HINT)


def render_reset_link(user: str, link: str) -> str:
    """Show the admin the freshly generated reset link for a user, to send out-of-band."""
    return _env.get_template("reset_link.html.j2").render(
        title="Сброс пароля — hashpass", nav=True, active="", user=user, link=link)


def history_href(user: str, ref: str, *, solved: bool) -> str:
    """
    Return the page of `user`'s work on `ref`; a solved one opens right at the solution.

    User 2026-10-25: «после нажатия на прогресс (галочку и остальное) хочу сразу решение».
    """
    href = f"/web/history?user={quote(user, safe='')}&ref={quote(ref, safe='')}"
    return f"{href}#solution" if solved else href


def _cell(user: str, ref: str, record: dict | None, summary: dict | None = None) -> dict:
    """
    One matrix cell (spec 2026-10-16): `·` not run, `◐` in progress, `✓` passed.

    «In progress» = the pool has sessions or a non-passing result, but no pass yet. A failed
    (digest-mismatch) result is in progress too: the student is still at it.
    """
    status = (record or {}).get("status")
    summary = summary or {}
    href = history_href(user, ref, solved=False)
    if status == "passed" or summary.get("passed"):
        verdict = ((record or {}).get("authenticity") or {}).get("verdict")
        pasted = verdict == "pasted"
        return {"mark": "✓⚠" if pasted else "✓", "cls": "c no" if pasted else "c ok",
                "href": history_href(user, ref, solved=True), "title": "зачтено" + (" (вставки)" if pasted else ""),
                "rank": 2 if pasted else 3}
    if status == "failed" or summary.get("sessions"):
        live = bool(summary.get("live"))
        return {"mark": "◐", "cls": "c run live" if live else "c run", "href": href,
                "title": "выполняется — сейчас решает" if live else "выполняется", "rank": 1}
    return {"mark": "", "cls": "c", "href": "", "title": "не выполнялось", "rank": 0}



_AUTHOR_GROUP = "authors"


def _dashboard_group_of(profile: dict) -> str:
    """Group on the dashboard: the user's own; authors/admins without one share `authors`."""
    group = str(profile.get("group", ""))
    if not group and profile.get("role") in ("author", "admin"):   # `author`: an old profile
        return _AUTHOR_GROUP
    return group


def render_dashboard(profiles: list[dict], entries: list[dict],
                     progress: dict[str, dict], *, group: str | None = None,
                     attempts: dict[str, dict] | None = None) -> str:
    # Students appear under their real class group; authors/admins share a synthetic `authors`
    # group so they can test-solve alongside (not mixed into) the student roster.
    """Progress matrix: users (login + group, comment on hover) × task numbers, cells passed/failed."""
    users = list(profiles)
    for p in users:
        p["_dash_group"] = _dashboard_group_of(p)
    groups = sorted({p["_dash_group"] for p in users if p["_dash_group"]})
    if group:
        users = [p for p in users if p["_dash_group"] == group]
    rows = []
    for p in users:
        user = str(p["user"])
        done = progress.get(user, {})
        seen = (attempts or {}).get(user, {})
        cells = [_cell(user, str(e["ref"]), done.get(str(e["ref"])), seen.get(str(e["ref"])))
                 for e in entries]
        passed = sum(1 for c in cells if c["mark"].startswith("✓"))
        rows.append({"user": user, "user_q": quote(user, safe=""), "group": p["_dash_group"],
                     "comment": str(p.get("comment", "")),
                     "passed": passed, "total": len(entries), "cells": cells})
    return _env.get_template("dashboard.html.j2").render(
        title="Прогресс — hashpass", nav=True, active="/web",
        entries=entries, rows=rows, groups=groups)


def _history_rows(items: list[dict], ref_set: set[str]) -> list[dict]:
    """Shape commands for the history table: speed, paste/reference flags, output."""
    rows = []
    for h in items:
        cmd = str(h.get("command", ""))
        typing = h.get("typing")
        speed = (f"{len(cmd) / typing:.0f} зн/с"
                 if isinstance(typing, (int, float)) and typing > 0 else "—")
        rows.append({"command": cmd, "speed": speed, "pasted": bool(h.get("pasted")),
                     "is_ref": _norm_cmd(cmd) in ref_set if ref_set else False,
                     "output": str(h.get("output") or "").rstrip("\n")})
    return rows


_OUTCOMES = {"passed": "зачтено", "abandoned": "вышел", "failed": "не принято"}


def _session_view(rec: dict, ref_set: set[str], now: float | None) -> dict:
    """One console session for the history page: when, how long, outcome, commands."""
    started, updated = rec.get("started"), rec.get("updated")
    when = ts_html(started) if isinstance(started, (int, float)) else ""
    mins = (int((float(updated) - float(started)) // 60)
            if isinstance(started, (int, float)) and isinstance(updated, (int, float)) else 0)
    live = is_live(rec, now)
    final = str(rec.get("final") or "")
    return {"id": safe_id(str(rec.get("session_id") or "")),
            "when": when, "duration": f"{mins} мин" if mins else "< 1 мин",
            "outcome": "идёт сейчас" if live else _OUTCOMES.get(final, "оборвалась"),
            "live": live, "truncated": bool(rec.get("truncated")),
            "rows": _history_rows(list(rec.get("entries") or []), ref_set)}


def _history_context(user: str, ref: str, record: dict,  # noqa: PLR0913
                     *, ref_commands: list[str] | None = None,
                     sessions: list[dict] | None = None, now: float | None = None) -> dict:
    """
    Everything the history page shows about one student's work on one task.

    Spec 2026-10-16: the passed session (the solution) on top, the other sessions (newest
    first) under it, each command with its output -- the teacher sees what does not work. The
    anti-bot flags (`вставка`, `эталон`) and the counts describe the solution, else the latest
    session, else -- a record from before sessions -- the submitted command history.
    """
    ref_set = {c for c in (ref_commands or []) if c}
    sessions = list(sessions or [])
    solution = next((s for s in sessions if s.get("final") == "passed"), None)
    others = [s for s in sessions if s is not solution]
    shown = solution or (sessions[0] if sessions else None)
    rows = (_history_rows(list(shown.get("entries") or []), ref_set) if shown
            else _history_rows(list(record.get("history", [])), ref_set))
    matches = sum(1 for r in rows if r["is_ref"])
    auth = record.get("authenticity") or {}
    typed_n = int(auth.get("typed", 0)) if not shown else sum(1 for r in rows if not r["pasted"])
    pasted_n = int(auth.get("pasted", 0)) if not shown else sum(1 for r in rows if r["pasted"])
    total = len(rows) or (typed_n + pasted_n)
    views = [_session_view(s, ref_set, now) for s in others]
    # What changes when the student types: the poll answers 204 while it stays the same.
    sig = hashlib.sha256(json.dumps(
        [[s.get("session_id"), len(s.get("entries") or []), s.get("final"), is_live(s, now)]
         for s in sessions] + [record.get("status"), len(record.get("history") or [])],
        default=str).encode()).hexdigest()[:16]
    return {"user": user, "ref": ref, "status": str(record.get("status", "")),
            "user_q": quote(user, safe=""), "ref_q": quote(ref, safe=""),
            "ref_url": quote(ref, safe="/:"),
            "total": total, "typed": typed_n, "pasted": pasted_n,
            "matches": matches, "extras": max(0, total - matches), "has_ref": bool(ref_set),
            "rows": [] if sessions else rows,
            "solution": _session_view(solution, ref_set, now) if solution else None,
            "attempts": views, "live": any(v["live"] for v in views), "sig": sig}


def render_history(user: str, ref: str, record: dict,  # noqa: PLR0913
                   *, ref_commands: list[str] | None = None,
                   sessions: list[dict] | None = None, now: float | None = None) -> str:
    """Render one student's work on one task; the page then polls `render_history_live`."""
    ctx = _history_context(user, ref, record, ref_commands=ref_commands,
                           sessions=sessions, now=now)
    return _env.get_template("history.html.j2").render(
        title="История — hashpass", nav=True, active="/web", **ctx)


def render_history_live(user: str, ref: str, record: dict,  # noqa: PLR0913
                        *, ref_commands: list[str] | None = None,
                        sessions: list[dict] | None = None,
                        now: float | None = None) -> tuple[str, str]:
    """Return the history page's live part (no page around it) and its change signature."""
    ctx = _history_context(user, ref, record, ref_commands=ref_commands,
                           sessions=sessions, now=now)
    return _env.get_template("_history_live.html.j2").render(**ctx), str(ctx["sig"])


def _fmt_size(n: object) -> str:
    size = int(n) if isinstance(n, (int, float)) else 0
    return f"{size} Б" if size < 1024 else f"{size / 1024:.0f} КБ"  # noqa: PLR2004


def _prepare_files(files: list[dict]) -> list[dict]:
    return [{"name": str(f.get("name", "")),
             "name_q": quote(str(f.get("name", "")), safe=""),
             "size_ru": _fmt_size(f.get("size")),
             "taskfile": bool(f.get("taskfile"))} for f in files]


def _about_parts(text: str) -> tuple[str, list[str]]:
    """Split an about.md into its `# title` and paragraphs (blank-line separated), for the card."""
    lines = text.strip().splitlines()
    title = lines[0][2:].strip() if lines and lines[0].startswith("# ") else ""
    body = "\n".join(lines[1:] if title else lines)
    return title, [p.strip() for p in body.split("\n\n") if p.strip()]


def _prepare_image(row: dict) -> dict:
    """Shape one image row (ref + files + description) for a template."""
    ref = str(row["ref"])
    files = row.get("files") if isinstance(row.get("files"), list) else []
    hidden = bool(row.get("hidden", False))
    return {"ref": ref, "ref_q": quote(ref, safe=""), "ref_url": quote(ref, safe="/:"),
            "kind": str(row.get("kind", "image")), "number": row.get("number"),
            "block_name": str(row.get("block_name", "")),
            "description": str(row.get("description", "")),
            "about": _about_parts(str(row.get("description", ""))),
            "hidden": hidden, "files": _prepare_files(files),
            "moderation": str(row.get("state") or ""), "reason": str(row.get("reason") or ""),
            "pending_update": bool(row.get("pending_update", False)),
            "sources": source_tree(ref, list(row.get("sources") or []))
            if row.get("sources") else None}


def render_catalog(images: list[dict], blocks: list[dict]) -> str:
    """Render the catalog editor (blocks + tasks with drag-reorder, no inline image cards)."""
    task_refs = [str(r["ref"]) for r in images if r.get("kind") == "task"]
    by_ref = {str(r["ref"]): r for r in images}
    prepared_blocks = []
    for b in blocks:
        tasks = []
        for e in b.get("tasks", []):
            ref = str(e.get("ref", ""))
            img = by_ref.get(ref, {})
            tasks.append({"ref": ref, "number": e.get("number"),
                          "hidden": bool(e.get("hidden") or img.get("hidden")),
                          "ref_url": quote(ref, safe="/:")})
        prepared_blocks.append({"id": str(b.get("id", "")), "name": str(b.get("name", "")),
                                "open": bool(b.get("open", True)), "tasks": tasks})
    all_images = [{"ref": str(r["ref"]), "ref_url": quote(str(r["ref"]), safe="/:"),
                   "kind": str(r.get("kind", "image")), "number": r.get("number")}
                  for r in images]
    return _env.get_template("catalog.html.j2").render(
        title="Каталог — hashpass", nav=True, active="/web/images",
        blocks=prepared_blocks, task_refs=task_refs, all_images=all_images)


# Kept for the routing seam: /web/images renders the catalog editor.
render_images = render_catalog


def render_image_card(image: dict, **extra: object) -> str:
    """Render one image's dedicated page (description, sources, files; revisions and courses)."""
    return _env.get_template("image_card.html.j2").render(
        title=f"{image.get('ref', '')} — hashpass", nav=True, active="/web/images",
        image=_prepare_image(image), **extra)


def render_repo_settings(repo: str, repo_info: dict, *, people: list[dict], role_ru: dict) -> str:
    """Render an image's settings page: visibility, tags, collaborators (owner only)."""
    return _env.get_template("repo_settings.html.j2").render(
        title=f"Настройки {repo} — hashpass", nav=True, active="", repo=repo, repo_info=repo_info,
        people=people, role_ru=role_ru)


def render_versions(repo: str, repo_info: dict, *, owner: bool) -> str:
    """Render all versions of one repository (its own page, like GitHub's commits)."""
    return _env.get_template("versions.html.j2").render(
        title=f"Версии {repo} — hashpass", nav=True, active="", repo=repo, repo_info=repo_info,
        owner=owner)


def _children(sources: list[dict], folder: str) -> list[dict]:
    """Direct entries of one folder of a task's sources: folders first, then files, by name."""
    prefix = f"{folder}/" if folder else ""
    rows = []
    for f in sources:
        path = str(f["path"])
        if not path.startswith(prefix) or "/" in path[len(prefix):]:
            continue
        rows.append({"name": path[len(prefix):], "path_q": quote(path, safe=""),
                     "dir": bool(f.get("dir")),
                     "size_ru": "" if f.get("dir") else _fmt_size(f.get("size"))})
    return sorted(rows, key=lambda r: (not r["dir"], r["name"].lower()))


def _crumbs(path: str) -> list[dict]:
    """Breadcrumbs of a source path: each folder links to its listing, the last part is plain."""
    parts = [p for p in path.split("/") if p]
    return [{"name": name, "path_q": quote("/".join(parts[:i + 1]), safe="")}
            for i, name in enumerate(parts)]


def source_tree(ref: str, sources: list[dict], folder: str = "") -> dict:
    """Build the GitHub-like file box of one folder (used by the card and the folder page)."""
    files = sum(1 for f in sources if not f.get("dir"))
    return {"ref_q": quote(ref, safe=""), "folder": folder,
            "up_q": quote(folder.rpartition("/")[0], safe="") if folder else None,
            "rows": _children(sources, folder), "files": files}


def render_source_file(ref: str, path: str, text: str | None, size: int,  # noqa: PLR0913
                       *, sources: list[dict] | None = None, is_dir: bool = False) -> str:
    """One source file (numbered, highlighted lines; Markdown also as a preview) or one folder."""
    lines = highlight_lines(path, text) if text is not None else []
    preview = (render_markdown_html(text)
               if text is not None and path.lower().endswith((".md", ".markdown")) else None)
    return _env.get_template("source_file.html.j2").render(
        title=f"{path} — {ref}", nav=True, active="/web/images",
        ref=ref, ref_url=quote(ref, safe="/:"), ref_q=quote(ref, safe=""),
        path=path, path_q=quote(path, safe=""), crumbs=_crumbs(path),
        text=text, size=size, size_ru=_fmt_size(size), lines=lines, preview=preview,
        nlines=_plural(len(lines), "строка", "строки", "строк"),
        tree=source_tree(ref, sources or [], path) if is_dir else None)


def _plural(n: int, one: str, few: str, many: str) -> str:
    """`2 строки`, `5 строк`, `21 строка` -- Russian count agreement."""
    if n % 10 == 1 and n % 100 != 11:  # noqa: PLR2004
        word = one
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:  # noqa: PLR2004
        word = few
    else:
        word = many
    return f"{n} {word}"


_ROLES = ("user", "admin")


def render_users(profiles: list[dict], *, registration_open: bool, current_user: str = "",  # noqa: PLR0913
                 pool_auto: bool = False, q: str = "", deletions: list[dict] | None = None,
                 owner: str = "", boxes: frozenset[str] = frozenset()) -> str:
    """User management: per-user role change / reset link / delete, delete-group, registration toggle."""
    rows = [{"user": str(p["user"]), "user_q": quote(str(p["user"]), safe=""),
             "created_at": p.get("created_at") or None,
             "group": str(p.get("group", "")),
             "role": str(p.get("role", "user")),
             "comment": str(p.get("comment", "")),
             "auto_approve": bool(p.get("auto_approve", False)),
             "perms": list(p.get("perms") or []),
             "is_owner": str(p["user"]) == owner,
             "is_self": str(p["user"]) == current_user} for p in profiles]
    return _env.get_template("users.html.j2").render(
        title="Пользователи — hashpass", nav=True, active="/web/users",
        rows=rows, roles=_ROLES, pool_auto=pool_auto, q=q, deletions=deletions or [],
        boxes=boxes, perm_labels=perms.LABELS,
        reg_label="открыта" if registration_open else "закрыта",
        toggle_to="false" if registration_open else "true",
        toggle_label="Закрыть регистрацию" if registration_open else "Открыть регистрацию")


def _duration(seconds: float) -> str:
    mins = int(seconds // 60)
    if mins < 1:
        return "< 1 мин"
    return f"{mins // 60} ч {mins % 60} мин" if mins >= 60 else f"{mins} мин"  # noqa: PLR2004


_STATUS_RU = {"✓": "зачтено", "✓⚠": "зачтено (вставки)", "◐": "выполняется", "": "не начато"}


def _profile_row(user: str, number: object, ref: str, record: dict | None,
                 recs: list[dict]) -> dict:
    """One task on a profile: status, tries, time spent, last activity, credited at."""
    summary = {"sessions": len(recs), "passed": any(r.get("final") == "passed" for r in recs),
               "live": any(is_live(r) for r in recs)}
    cell = _cell(user, ref, record, summary)
    spent = sum(max(0.0, float(r.get("updated") or 0) - float(r.get("started") or 0))
                for r in recs if isinstance(r.get("started"), (int, float)))
    last = max([float(r.get("updated") or r.get("started") or 0) for r in recs] +
               [_epoch((record or {}).get("ts")) or 0.0])
    passed_at = ((record or {}).get("ts") if (record or {}).get("status") == "passed"
                 else max((r.get("updated") for r in recs if r.get("final") == "passed"),
                          default=None, key=lambda v: float(v or 0)))
    return {"number": number if number is not None else "", "ref": ref,
            "ref_url": quote(ref, safe="/:"), "cell": cell,
            "status": _STATUS_RU.get(cell["mark"], ""), "tries": len(recs),
            "spent": _duration(spent) if recs else "—", "spent_s": int(spent),
            "last": last or None, "passed_at": passed_at,
            "passed_s": _epoch(passed_at) or 0}


def render_profile(profile: dict, entries: list[dict], progress: dict[str, dict],  # noqa: PLR0913
                   sessions: dict[str, list[dict]], *, course: dict | None = None,
                   about: dict[str, str] | None = None) -> str:
    """
    One user's page: who they are + every catalog task with status, tries, time and links.

    Tasks off the catalog that still carry progress (removed / renamed) are listed after it,
    so nothing the student did disappears from view.
    """
    user = str(profile["user"])
    refs = [str(e["ref"]) for e in entries]
    rows = [_profile_row(user, e.get("number"), str(e["ref"]),
                         progress.get(str(e["ref"])), list(sessions.get(str(e["ref"])) or []))
            for e in entries]
    extra = sorted((set(progress) | set(sessions)) - set(refs))
    rows += [_profile_row(user, None, ref, progress.get(ref), list(sessions.get(ref) or []))
             for ref in extra]
    passed = sum(1 for r in rows[:len(entries)] if r["cell"]["mark"].startswith("✓"))
    if course is not None:                   # a student inside one course: only its tasks
        rows = rows[:len(entries)]
    for r in rows:
        r["about"] = (about or {}).get(r["ref"], "")
        if course is not None and r["cell"]["mark"].startswith("✓") and outside_course(
                progress.get(r["ref"]), str(course.get("ref", "")), course.get("former") or ()):
            r["status"] += " не в курсе"            # solved by `hashpass run` or in another course
        r["state"] = "passed" if r["cell"]["mark"].startswith("✓") else ("started" if r["cell"]["mark"] else "none")
    started = sum(1 for r in rows if r["state"] == "started")
    stats = {"passed": passed, "started": started, "none": len(rows) - passed - started,
             "tries": sum(int(r["tries"]) for r in rows),
             "spent": _duration(sum(int(r["spent_s"]) for r in rows)) if any(r["tries"] for r in rows) else "—"}
    return _env.get_template("profile.html.j2").render(
        title=f"{user} — hashpass", nav=True, active="/c" if course else "/web", course=course, stats=stats,
        p={"user": user, "role": str(profile.get("role", "")),
           "group": str(profile.get("group", "")), "comment": str(profile.get("comment", "")),
           "created_at": profile.get("created_at") or None},
        rows=rows, passed=passed, total=len(entries), off_catalog=len(extra))


def render_settings(*, tz: str, zones: list[str], error: str = "", done: str = "") -> str:
    """Render the viewer's settings: time zone (default -- the browser's) and password change."""
    return _env.get_template("password.html.j2").render(
        title="Настройки — hashpass", nav=True, active="/web/settings",
        tz=tz, zones=zones, error=error, done=done, hint=_PW_HINT, now=time.time())


def render_compare(name: str, old: str, new: str, files: list[dict]) -> str:
    """Two versions side by side: what changed, file by file (spec 2026-10-23 §3)."""
    counts = {k: sum(1 for f in files if f["change"] == k) for k in ("added", "removed", "changed")}
    return _env.get_template("compare.html.j2").render(
        title=f"{name}: сравнение — hashpass", nav=True, active="", name=name, old=old, new=new,
        files=files, counts=counts)
