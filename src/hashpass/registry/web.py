"""Server-rendered web dashboard for the pool (Jinja2 templates): install scripts + render_* HTML."""
import time
from pathlib import Path
from urllib.parse import quote

from flask import g, has_request_context
from jinja2 import Environment, FileSystemLoader, select_autoescape

from hashpass.registry.attempt_store import is_live
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


_INSTALL_TEMPLATE = """\
#!/usr/bin/env bash
# hashpass __ROLE__ installer -- served by the pool at __POOL__
set -euo pipefail
POOL="__POOL__"
echo "Установка hashpass (__ROLE__); пул: $POOL"
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
elif command -v dnf >/dev/null 2>&1; then
  PKG_REFRESH=":"; PKG_INSTALL="sudo dnf install -y"
  P_PY=python3; P_PIP=python3-pip; P_NSPAWN=systemd-container
else
  # A fresh Debian/Ubuntu has stale package lists -> «Unable to locate package» without an update.
  # noninteractive: tzdata/needrestart must not stop the install with a dialog
  PKG_REFRESH="sudo apt update"; PKG_INSTALL="sudo env DEBIAN_FRONTEND=noninteractive apt install -y"
  P_PY=python3; P_PIP=python3-pip; P_NSPAWN=systemd-container
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
if ! "$PY" -m pip --version >/dev/null 2>&1; then   # deadsnakes/uv Pythons come without pip
  if ! "$PY" -m ensurepip --user >/dev/null 2>&1; then
    GETPIP="$(mktemp)"
    curl -fsSL -o "$GETPIP" https://bootstrap.pypa.io/get-pip.py \
      || curl -kfsSL -o "$GETPIP" https://bootstrap.pypa.io/get-pip.py
    "$PY" "$GETPIP" --user --break-system-packages \
      || PIP_TRUSTED_HOST="$TRUSTED" "$PY" "$GETPIP" --user --break-system-packages
    rm -f "$GETPIP"
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
pip_install --upgrade "flask>=3.0" "textual>=1.0"
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

_ENGINE_ACTIVATE = 'mkdir -p "$HOME/.hashengine" && touch "$HOME/.hashengine/engine.enabled"'


def _install_script(pool_url: str, *, role: str, nxt: str, extra: str = ":") -> str:
    return (_INSTALL_TEMPLATE
            .replace("__POOL__", pool_url.rstrip("/"))
            .replace("__REPO__", _REPO)
            .replace("__TRUSTED__", " ".join(TRUSTED_HOSTS))
            .replace("__ROLE__", role)
            .replace("__EXTRA__", extra)
            .replace("__NEXT__", nxt))


def render_install_script(pool_url: str) -> str:
    """Return the student install script (installs `hashpass`, seeds the pool URL into pool.json)."""
    return _install_script(pool_url, role="student", nxt="Запустите:  hashpass   (без sudo — пароль sudo он спросит сам)")


def render_engine_install_script(pool_url: str) -> str:
    """Return the author-gated engine install script (installs + activates hashengine here)."""
    return _install_script(pool_url, role="engine", nxt="hashengine установлен.",
                           extra=_ENGINE_ACTIVATE)


_PW_HINT = "Не короче 8 символов, минимум одна буква, одна цифра и один спецсимвол."


# What the front page has the student run BEFORE install.sh, per package manager (the script
# re-checks and installs anything still missing). systemd-nspawn ships in Arch's base `systemd`.
PREPARE = (
    ("apt", "apt (Debian, Ubuntu)",
     ("sudo apt update", "sudo apt install -y curl git python3-pip systemd-container")),
    ("pacman", "pacman (Arch)",
     ("sudo pacman -Syu --needed --noconfirm curl git python python-pip",)),
)


def render_front(pool_url: str) -> str:
    """Public front page: what the pool is + prepare-the-system steps (apt/pacman) + install.sh."""
    url = pool_url.rstrip("/")
    # A self-signed HTTPS pool needs curl -k to fetch the installer (the pip step uses GitHub's
    # real cert, so it is unaffected); a plain-http pool does not.
    flags = "-fsSLk" if pool_url.startswith("https://") else "-fsSL"
    return _env.get_template("front.html.j2").render(
        title="hashpass", nav=False, active="", url=url, flags=flags, prepare=PREPARE)


def render_login(error: str = "", *, signed_in: str = "", role: str = "") -> str:
    """Teacher/admin login form; `signed_in` -- who is already in (sent here by an admin-only page)."""
    return _env.get_template("login.html.j2").render(
        title="Вход — hashpass", nav=False, active="", error=error,
        signed_in=signed_in, role={"author": "автор", "admin": "администратор"}.get(role, role))


def render_password_form(error: str = "", *, done: bool = False) -> str:
    """Change-own-password form (for a logged-in author/admin)."""
    return _env.get_template("password.html.j2").render(
        title="Пароль — hashpass", nav=True, active="",
        error=error, done=done, hint=_PW_HINT)


def render_reset_form(token: str, error: str = "") -> str:
    """Set-a-new-password form reached via an admin-issued reset link (no login needed)."""
    return _env.get_template("reset.html.j2").render(
        title="Восстановление — hashpass", nav=False, active="",
        token=token, error=error, hint=_PW_HINT)


def render_reset_link(user: str, link: str) -> str:
    """Show the admin the freshly generated reset link for a user, to send out-of-band."""
    return _env.get_template("reset_link.html.j2").render(
        title="Сброс пароля — hashpass", nav=True, active="", user=user, link=link)


def _cell(user: str, ref: str, record: dict | None, summary: dict | None = None) -> dict:
    """
    One matrix cell (spec 2026-10-16): `·` not run, `◐` in progress, `✓` passed.

    «In progress» = the pool has sessions or a non-passing result, but no pass yet. A failed
    (digest-mismatch) result is in progress too: the student is still at it.
    """
    status = (record or {}).get("status")
    summary = summary or {}
    href = f"/web/history?user={quote(user, safe='')}&ref={quote(ref, safe='')}"
    if status == "passed" or summary.get("passed"):
        verdict = ((record or {}).get("authenticity") or {}).get("verdict")
        pasted = verdict == "pasted"
        return {"mark": "✓⚠" if pasted else "✓", "cls": "c no" if pasted else "c ok",
                "href": href, "title": "зачтено" + (" (вставки)" if pasted else "")}
    if status == "failed" or summary.get("sessions"):
        live = bool(summary.get("live"))
        return {"mark": "◐", "cls": "c run live" if live else "c run", "href": href,
                "title": "выполняется — сейчас решает" if live else "выполняется"}
    return {"mark": "", "cls": "c", "href": "", "title": "не выполнялось"}


_AUTHOR_GROUP = "authors"


def _dashboard_group_of(profile: dict) -> str:
    """Synthetic group for the dashboard: authors and admins go into a single `authors` bucket."""
    if profile.get("role") in ("author", "admin"):
        return _AUTHOR_GROUP
    return str(profile.get("group", ""))


def render_dashboard(profiles: list[dict], entries: list[dict],
                     progress: dict[str, dict], *, group: str | None = None,
                     attempts: dict[str, dict] | None = None) -> str:
    # Students appear under their real class group; authors/admins share a synthetic `authors`
    # group so they can test-solve alongside (not mixed into) the student roster.
    """Progress matrix: users (login + group, comment on hover) × task numbers, cells passed/failed."""
    users = [p for p in profiles if p.get("role") in ("student", "author", "admin")]
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
        rows.append({"user": user, "group": p["_dash_group"],
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
    when = (time.strftime("%d.%m %H:%M", time.localtime(float(started)))
            if isinstance(started, (int, float)) else "")
    mins = (int((float(updated) - float(started)) // 60)
            if isinstance(started, (int, float)) and isinstance(updated, (int, float)) else 0)
    live = is_live(rec, now)
    final = str(rec.get("final") or "")
    return {"when": when, "duration": f"{mins} мин" if mins else "< 1 мин",
            "outcome": "идёт сейчас" if live else _OUTCOMES.get(final, "оборвалась"),
            "live": live, "truncated": bool(rec.get("truncated")),
            "rows": _history_rows(list(rec.get("entries") or []), ref_set)}


def render_history(user: str, ref: str, record: dict,  # noqa: PLR0913
                   *, ref_commands: list[str] | None = None,
                   sessions: list[dict] | None = None, now: float | None = None) -> str:
    """
    Render one student's work on one task: the solution, then every attempt, with outputs.

    Spec 2026-10-16: the passed session (the solution) is open on top, the other sessions
    (newest first) fold under it, each command with its output -- the teacher sees what does not
    work. A session being solved right now makes the page refresh itself. The anti-bot flags
    (`вставка`, `эталон`) and the counts at the top stay; they describe the solution, else the
    latest session, else -- a record from before sessions -- the submitted command history.
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
    return _env.get_template("history.html.j2").render(
        title="История — hashpass", nav=True, active="/web",
        user=user, ref=ref, status=str(record.get("status", "")),
        total=total, typed=typed_n, pasted=pasted_n,
        matches=matches, extras=max(0, total - matches), has_ref=bool(ref_set),
        rows=[] if sessions else rows,
        solution=_session_view(solution, ref_set, now) if solution else None,
        attempts=views, live=any(v["live"] for v in views))


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
            "sources": [{**f, "path_q": quote(str(f["path"]), safe=""),
                         "depth": str(f["path"]).count("/"),
                         "name": str(f["path"]).rsplit("/", 1)[-1]}
                        for f in row.get("sources") or []]}


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


def render_image_card(image: dict) -> str:
    """Render one image's dedicated page (description editor + files)."""
    return _env.get_template("image_card.html.j2").render(
        title=f"{image.get('ref', '')} — hashpass", nav=True, active="/web/images",
        image=_prepare_image(image))


def render_source_file(ref: str, path: str, text: str | None, size: int) -> str:
    """One source file of a task: its text, or a note that it is binary."""
    return _env.get_template("source_file.html.j2").render(
        title=f"{path} — {ref}", nav=True, active="/web/images",
        ref=ref, ref_url=quote(ref, safe="/:"), path=path, text=text, size=size)


_ROLES = ("student", "author", "admin")


def render_users(profiles: list[dict], *, registration_open: bool, current_user: str = "",
                 pool_auto: bool = False) -> str:
    """User management: per-user role change / reset link / delete, delete-group, registration toggle."""
    rows = [{"user": str(p["user"]),
             "group": str(p.get("group", "")),
             "role": str(p.get("role", "student")),
             "comment": str(p.get("comment", "")),
             "auto_approve": bool(p.get("auto_approve", False)),
             "is_self": str(p["user"]) == current_user} for p in profiles]
    return _env.get_template("users.html.j2").render(
        title="Пользователи — hashpass", nav=True, active="/web/users",
        rows=rows, roles=_ROLES, pool_auto=pool_auto,
        reg_label="открыта" if registration_open else "закрыта",
        toggle_to="false" if registration_open else "true",
        toggle_label="Закрыть регистрацию" if registration_open else "Открыть регистрацию")
