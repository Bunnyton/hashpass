"""Server-rendered web dashboard for the pool (Jinja2 templates): install scripts + render_* HTML."""
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape

from hashpass.registry.reference import normalise as _norm_cmd

_REPO = "Bunnyton/hashpass"
_TEMPLATES = Path(__file__).parent / "templates"

# One module-level Jinja env so render_* stays a plain function (usable from tests without Flask).
_env = Environment(loader=FileSystemLoader(str(_TEMPLATES)),
                   autoescape=select_autoescape(("html", "j2", "html.j2")),
                   trim_blocks=False, lstrip_blocks=False)


_INSTALL_TEMPLATE = """\
#!/usr/bin/env bash
# hashpass __ROLE__ installer -- served by the pool at __POOL__
set -euo pipefail
POOL="__POOL__"
echo "Установка hashpass (__ROLE__); пул: $POOL"
# Preflight: everything the install needs must be present BEFORE we download anything.
# Package names and the install command follow the host's package manager (Debian/Ubuntu,
# Arch, Fedora); the task containers are Debian regardless of the host.
if command -v pacman >/dev/null 2>&1; then
  PKG_INSTALL="sudo pacman -S --needed --noconfirm"; P_PY=python; P_PIP=python-pip; P_NSPAWN=systemd
elif command -v dnf >/dev/null 2>&1; then
  PKG_INSTALL="sudo dnf install -y"; P_PY=python3; P_PIP=python3-pip; P_NSPAWN=systemd-container
else
  PKG_INSTALL="sudo apt install -y"; P_PY=python3; P_PIP=python3-pip; P_NSPAWN=systemd-container
fi
missing=""
command -v python3 >/dev/null 2>&1 || missing="$missing $P_PY"
python3 -m pip --version >/dev/null 2>&1 || missing="$missing $P_PIP"
command -v git >/dev/null 2>&1 || missing="$missing git"
command -v systemd-nspawn >/dev/null 2>&1 || missing="$missing $P_NSPAWN"
if [ -n "$missing" ]; then
  # Install them right here (sudo asks for the password on /dev/tty, so `curl | bash` works).
  echo "ставлю недостающие пакеты:$missing"
  # shellcheck disable=SC2086  # word-splitting of the command and the package list is intended
  if ! $PKG_INSTALL$missing </dev/tty; then
    echo "не удалось поставить:$missing" >&2
    echo "поставьте вручную и повторите:  $PKG_INSTALL$missing" >&2
    exit 1
  fi
fi
# `--upgrade --force-reinstall --no-deps`: pip normally sees "hashpass X.Y.Z is
# already installed" and does nothing -- even when the git branch has moved and
# we forgot to bump the version.  --force-reinstall reinstalls the package no
# matter what; --no-deps avoids touching flask/textual/etc. (which we already
# have from the first install and don't want to churn on every rerun).  If new
# runtime deps ever land, run install.sh a second time WITHOUT --no-deps, or
# `pip install --upgrade flask textual` by hand.
# --break-system-packages is needed on PEP 668 distros (Debian 12+, Ubuntu 23.04+) but an
# older pip (Ubuntu 22.04: pip 22.0) rejects the unknown flag -- pass it only when supported.
BSP=""
python3 -m pip install --help 2>/dev/null | grep -q -- --break-system-packages && BSP="--break-system-packages"
python3 -m pip install --user $BSP --upgrade --force-reinstall --no-deps \\
    "git+https://github.com/__REPO__@main"
python3 -m pip install --user $BSP --upgrade "flask>=3.0" "textual>=1.0"
# `pip --user` puts the commands into ~/.local/bin. Ubuntu's ~/.profile adds that dir to PATH
# only if it ALREADY existed at login, Arch never does -- so `hashpass` was «command not found».
# Persist it for bash (~/.bashrc + ~/.profile), zsh (~/.zshrc) and fish (conf.d), idempotently,
# and say how to pick it up in the terminal that is already open.
BIN="$(python3 -m site --user-base)/bin"
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


def render_front(pool_url: str) -> str:
    """Public front page: what the pool is + the one-line student install command."""
    url = pool_url.rstrip("/")
    # A self-signed HTTPS pool needs curl -k to fetch the installer (the pip step uses GitHub's
    # real cert, so it is unaffected); a plain-http pool does not.
    flags = "-fsSLk" if pool_url.startswith("https://") else "-fsSL"
    return _env.get_template("front.html.j2").render(
        title="hashpass", nav=False, active="", url=url, flags=flags)


def render_login(error: str = "") -> str:
    """Teacher/admin login form."""
    return _env.get_template("login.html.j2").render(
        title="Вход — hashpass", nav=False, active="", error=error)


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


def _cell(user: str, ref: str, record: dict | None) -> dict:
    """One matrix cell: {mark, cls, href} for a rendered result, {mark: ''} for an empty cell."""
    status = (record or {}).get("status")
    if status not in ("passed", "failed"):
        return {"mark": "", "cls": "c", "href": ""}
    verdict = ((record or {}).get("authenticity") or {}).get("verdict")
    href = f"/web/history?user={quote(user, safe='')}&ref={quote(ref, safe='')}"
    if status == "passed":
        return {"mark": "✓⚠" if verdict == "pasted" else "✓",
                "cls": "c no" if verdict == "pasted" else "c ok",
                "href": href}
    return {"mark": "✗", "cls": "c no", "href": href}


_AUTHOR_GROUP = "authors"


def _dashboard_group_of(profile: dict) -> str:
    """Synthetic group for the dashboard: authors and admins go into a single `authors` bucket."""
    if profile.get("role") in ("author", "admin"):
        return _AUTHOR_GROUP
    return str(profile.get("group", ""))


def render_dashboard(profiles: list[dict], entries: list[dict],
                     progress: dict[str, dict], *, group: str | None = None) -> str:
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
        cells = [_cell(user, str(e["ref"]), done.get(str(e["ref"]))) for e in entries]
        passed = sum(1 for e in entries if (done.get(str(e["ref"])) or {}).get("status") == "passed")
        rows.append({"user": user, "group": p["_dash_group"],
                     "comment": str(p.get("comment", "")),
                     "passed": passed, "total": len(entries), "cells": cells})
    return _env.get_template("dashboard.html.j2").render(
        title="Прогресс — hashpass", nav=True, active="/web",
        entries=entries, rows=rows, groups=groups)


def render_history(user: str, ref: str, record: dict,
                   *, ref_commands: list[str] | None = None) -> str:
    """
    Render one student's command history for one task, as anti-bot flags — no verdict.

    Flags on each command: `вставка` (client-supplied paste signal) and `эталон` (matches a
    reference `solve` command from the Taskfile). A small summary at the top gives raw counts
    (typed / pasted / matches-reference / extras); the teacher decides.
    """
    ref_set = {c for c in (ref_commands or []) if c}
    rows = []
    matches = 0
    for h in record.get("history", []):
        cmd = str(h.get("command", ""))
        typing = h.get("typing")
        speed = (f"{len(cmd) / typing:.0f} зн/с"
                 if isinstance(typing, (int, float)) and typing > 0 else "—")
        is_ref = _norm_cmd(cmd) in ref_set if ref_set else False
        matches += 1 if is_ref else 0
        rows.append({"command": cmd, "speed": speed,
                     "pasted": bool(h.get("pasted")), "is_ref": is_ref})
    auth = record.get("authenticity") or {}
    typed_n = int(auth.get("typed", 0))
    pasted_n = int(auth.get("pasted", 0))
    total = len(rows) or (typed_n + pasted_n)
    extras = max(0, total - matches)
    return _env.get_template("history.html.j2").render(
        title="История — hashpass", nav=True, active="/web",
        user=user, ref=ref, status=str(record.get("status", "")),
        total=total, typed=typed_n, pasted=pasted_n,
        matches=matches, extras=extras, has_ref=bool(ref_set), rows=rows)


def _fmt_size(n: object) -> str:
    size = int(n) if isinstance(n, (int, float)) else 0
    return f"{size} Б" if size < 1024 else f"{size / 1024:.0f} КБ"  # noqa: PLR2004


def _prepare_files(files: list[dict]) -> list[dict]:
    return [{"name": str(f.get("name", "")),
             "name_q": quote(str(f.get("name", "")), safe=""),
             "size_ru": _fmt_size(f.get("size")),
             "taskfile": bool(f.get("taskfile"))} for f in files]


def _prepare_image(row: dict) -> dict:
    """Shape one image row (ref + files + description) for a template."""
    ref = str(row["ref"])
    files = row.get("files") if isinstance(row.get("files"), list) else []
    hidden = bool(row.get("hidden", False))
    return {"ref": ref, "ref_q": quote(ref, safe=""), "ref_url": quote(ref, safe="/:"),
            "kind": str(row.get("kind", "image")), "number": row.get("number"),
            "block_name": str(row.get("block_name", "")),
            "description": str(row.get("description", "")),
            "hidden": hidden, "files": _prepare_files(files)}


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


_ROLES = ("student", "author", "admin")


def render_users(profiles: list[dict], *, registration_open: bool, current_user: str = "") -> str:
    """User management: per-user role change / reset link / delete, delete-group, registration toggle."""
    rows = [{"user": str(p["user"]),
             "group": str(p.get("group", "")),
             "role": str(p.get("role", "student")),
             "comment": str(p.get("comment", "")),
             "is_self": str(p["user"]) == current_user} for p in profiles]
    return _env.get_template("users.html.j2").render(
        title="Пользователи — hashpass", nav=True, active="/web/users",
        rows=rows, roles=_ROLES,
        reg_label="открыта" if registration_open else "закрыта",
        toggle_to="false" if registration_open else "true",
        toggle_label="Закрыть регистрацию" if registration_open else "Открыть регистрацию")
