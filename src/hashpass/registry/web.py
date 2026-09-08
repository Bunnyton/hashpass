"""Server-rendered web dashboard for the pool (stdlib only): front page, login, progress, users."""
from html import escape

_REPO = "Bunnyton/hashpass"

_INSTALL_TEMPLATE = """\
#!/usr/bin/env bash
# hashpass __ROLE__ installer -- served by the pool at __POOL__
set -euo pipefail
POOL="__POOL__"
echo "Установка hashpass (__ROLE__); пул: $POOL"
command -v python3 >/dev/null 2>&1 || { echo "нужен python3"; exit 1; }
python3 -m pip install --user --break-system-packages "git+https://github.com/__REPO__@main"
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
    return _install_script(pool_url, role="student", nxt="Запустите:  hashpass")


def render_engine_install_script(pool_url: str) -> str:
    """Return the author-gated engine install script (installs + activates hashengine here)."""
    return _install_script(pool_url, role="engine", nxt="hashengine установлен.",
                           extra=_ENGINE_ACTIVATE)

_STYLE = """
:root{color-scheme:light dark;
  --bg:#f4f5f8;--surface:#fff;--surface2:#f9fafb;--border:#e5e7eb;--text:#111827;
  --muted:#6b7280;--accent:#4f46e5;--accent-ink:#fff;--accent-hi:#4338ca;
  --good:#16a34a;--bad:#dc2626;--chip:#eef2ff;--chip-ink:#3730a3}
:root[data-theme=dark],:root:not([data-theme=light]) @media (prefers-color-scheme:dark){}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#0d1117;--surface:#161b22;--surface2:#1c2230;--border:#30363d;--text:#e6edf3;
  --muted:#9aa4b2;--accent:#6d64f5;--accent-hi:#8b83ff;--chip:#232a4d;--chip-ink:#c7d0ff}}
*{box-sizing:border-box}
body{font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;
  background:var(--bg);color:var(--text)}
.nav{position:sticky;top:0;z-index:5;background:var(--surface);border-bottom:1px solid var(--border);
  display:flex;gap:6px;align-items:center;padding:10px 22px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.nav .brand{font-weight:800;letter-spacing:.5px;margin-right:14px}
.nav .brand b{color:var(--accent)}
.nav a{color:var(--muted);text-decoration:none;padding:6px 11px;border-radius:8px;font-weight:500}
.nav a:hover{background:var(--surface2);color:var(--text)}
.nav .sp{flex:1}
main{max-width:1080px;margin:0 auto;padding:26px 22px 60px}
h1{font-size:23px;margin:.1em 0 .1em;letter-spacing:-.01em;text-wrap:balance}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
  margin:1.8em 0 .7em;font-weight:700}
.sub{color:var(--muted);margin:.2em 0 1.2em}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 20px;
  box-shadow:0 1px 2px rgba(0,0,0,.04);max-width:440px;margin:0 0 14px}
.wide{max-width:none}
table{border-collapse:separate;border-spacing:0;width:100%;background:var(--surface);
  border:1px solid var(--border);border-radius:12px;overflow:hidden;
  box-shadow:0 1px 2px rgba(0,0,0,.04);font-variant-numeric:tabular-nums}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--border)}
th{background:var(--surface2);font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
tr:last-child td{border-bottom:0}
tbody tr:hover td,table tr:hover td{background:var(--surface2)}
td.c,th.c{text-align:center}
.ok{color:var(--good);font-weight:800}.no{color:var(--bad);font-weight:700}.dim{color:var(--muted)}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;background:var(--chip);
  color:var(--chip-ink);font-size:12px;font-weight:600}
.pill.admin{background:#fde68a;color:#92400e}.pill.author{background:#bbf7d0;color:#166534}
label{display:block;margin-top:12px;font-size:12px;font-weight:600;text-transform:uppercase;
  letter-spacing:.04em;color:var(--muted)}
input,select{font:inherit;width:100%;padding:9px 11px;margin-top:5px;border:1px solid var(--border);
  border-radius:9px;background:var(--surface);color:var(--text)}
input:focus,select:focus{outline:2px solid var(--accent);outline-offset:0;border-color:var(--accent)}
.btn,button{font:inherit;font-weight:600;padding:9px 15px;margin-top:12px;border:1px solid var(--accent);
  border-radius:9px;background:var(--accent);color:var(--accent-ink);cursor:pointer;text-decoration:none;
  display:inline-block}
.btn:hover,button:hover{background:var(--accent-hi);border-color:var(--accent-hi)}
.btn.ghost{background:transparent;color:var(--accent);}
.btn.ghost:hover{background:var(--chip)}
.btn.sm,button.sm{padding:5px 10px;margin:0;font-size:13px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
form.inline{margin:0}form.inline select{width:auto;margin:0}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.code{display:block;background:var(--surface2);border:1px solid var(--border);border-radius:9px;
  padding:11px 13px;overflow-x:auto;font-family:ui-monospace,Menlo,monospace;font-size:13px}
.err{background:#fef2f2;color:#991b1b;border:1px solid #fecaca;border-radius:9px;padding:9px 12px;margin:10px 0}
.note{background:var(--chip);color:var(--chip-ink);border-radius:9px;padding:9px 12px;margin:10px 0}
@media(prefers-color-scheme:dark){.err{background:#3b1216;color:#fecaca;border-color:#5b1a20}}
"""


def _page(title: str, body: str, *, nav: bool = True) -> str:
    header = ("<div class='nav'><span class='brand'>hash<b>pass</b></span>"
              "<a href='/web'>Прогресс</a><a href='/web/images'>Образы</a>"
              "<a href='/web/users'>Пользователи</a><span class='sp'></span>"
              "<a href='/web/password'>Пароль</a><a href='/web/logout'>Выход</a></div>") if nav else ""
    return (f"<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{escape(title)}</title><style>{_STYLE}</style></head>"
            f"<body>{header}<main>{body}</main></body></html>")


def _field(label: str, name: str, *, kind: str = "text", extra: str = "") -> str:
    return f"<label>{escape(label)}<input name='{name}' type='{kind}' {extra}></label>"


def render_front(pool_url: str) -> str:
    """Public front page: what the pool is + the one-line student install command."""
    url = escape(pool_url.rstrip("/"))
    body = ("<h1>hashpass — учебный пул</h1>"
            "<p class='sub'>Интерактивные задания по Linux в живой консоли Debian. "
            "Установка студенту — одной командой:</p>"
            f"<code class='code'>curl -fsSL {url}/install.sh | bash</code>"
            "<p style='margin-top:18px'><a class='btn' href='/web/login'>Вход для преподавателя</a></p>")
    return _page("hashpass", body, nav=False)


def render_login(error: str = "") -> str:
    """Teacher/admin login form."""
    err = f"<div class='err'>{escape(error)}</div>" if error else ""
    body = (f"<h1>Вход преподавателя</h1><p class='sub'>Доступ к прогрессу и управлению.</p>{err}"
            "<form class='card' method='post' action='/web/login'>"
            + _field("Логин", "user", extra="autofocus")
            + _field("Пароль", "password", kind="password")
            + "<button type='submit'>Войти</button></form>")
    return _page("Вход — hashpass", body, nav=False)


def render_password_form(error: str = "", *, done: bool = False) -> str:
    """Change-own-password form (for a logged-in author/admin)."""
    msg = "<div class='note'>Пароль изменён.</div>" if done else ""
    err = f"<div class='err'>{escape(error)}</div>" if error else ""
    body = (f"<h1>Смена пароля</h1>{msg}{err}"
            "<form class='card' method='post' action='/web/password'>"
            + _field("Текущий пароль", "old", kind="password", extra="autofocus")
            + _field("Новый пароль", "new", kind="password")
            + _field("Повторите новый", "confirm", kind="password")
            + "<button type='submit'>Сменить</button></form>")
    return _page("Пароль — hashpass", body)


def render_reset_form(token: str, error: str = "") -> str:
    """Set-a-new-password form reached via an admin-issued reset link (no login needed)."""
    err = f"<div class='err'>{escape(error)}</div>" if error else ""
    body = (f"<h1>Новый пароль</h1><p class='sub'>Задайте пароль по ссылке восстановления.</p>{err}"
            "<form class='card' method='post' action='/web/reset'>"
            f"<input type='hidden' name='token' value='{escape(token)}'>"
            + _field("Новый пароль", "new", kind="password", extra="autofocus")
            + _field("Повторите", "confirm", kind="password")
            + "<button type='submit'>Сохранить</button></form>")
    return _page("Восстановление — hashpass", body, nav=False)


def render_reset_link(user: str, link: str) -> str:
    """Show the admin the freshly generated reset link for a user, to send out-of-band."""
    body = (f"<h1>Ссылка для сброса пароля</h1>"
            f"<p class='sub'>Отправьте её пользователю <b>{escape(user)}</b> (действует ограниченно):</p>"
            f"<code class='code'>{escape(link)}</code>"
            "<p style='margin-top:16px'><a class='btn ghost' href='/web/users'>← к пользователям</a></p>")
    return _page("Сброс пароля — hashpass", body)


def _cell(status: str | None) -> str:
    if status == "passed":
        return "<td class='c ok'>✓</td>"
    if status == "failed":
        return "<td class='c no'>✗</td>"
    return "<td class='c'>·</td>"


def render_dashboard(profiles: list[dict], entries: list[dict],
                     progress: dict[str, dict], *, group: str | None = None) -> str:
    """Progress matrix: students (login + group, comment on hover) × task numbers, cells passed/failed."""
    students = [p for p in profiles if p.get("role") == "student"]
    groups = sorted({str(p.get("group", "")) for p in students if p.get("group")})
    if group:
        students = [p for p in students if str(p.get("group", "")) == group]
    picker = " ".join(
        f"<a class='pill' href='/web?group={escape(g)}'>{escape(g)}</a>" for g in groups)
    picker = f"<p>Группы: <a class='pill' href='/web'>все</a> {picker}</p>" if groups else ""
    head = "".join(f"<th title='{escape(str(e['title']))}'>{e['number']}</th>" for e in entries)
    rows = []
    for p in students:
        user = str(p["user"])
        done = progress.get(user, {})
        cells = "".join(_cell((done.get(str(e["ref"])) or {}).get("status")) for e in entries)
        passed = sum(1 for e in entries if (done.get(str(e["ref"])) or {}).get("status") == "passed")
        rows.append(f"<tr><td title='{escape(str(p.get('comment', '')))}'>{escape(user)}</td>"
                    f"<td>{escape(str(p.get('group', '')))}</td>"
                    f"<td class='c'>{passed}/{len(entries)}</td>{cells}</tr>")
    table = (f"<table><tr><th>Логин</th><th>Группа</th><th>Σ</th>{head}</tr>"
             f"{''.join(rows) or '<tr><td colspan=99>нет студентов</td></tr>'}</table>")
    return _page("Прогресс — hashpass", f"<h1>Прогресс студентов</h1>{picker}{table}")


def render_images(images: list[dict]) -> str:
    """List the images/tasks the pool holds (ref, kind, catalog number for tasks)."""
    rows = "".join(
        f"<tr><td>{escape(str(i['ref']))}</td><td>{escape(str(i['kind']))}</td>"
        f"<td class='c'>{i['number'] if i.get('number') is not None else ''}</td></tr>"
        for i in images)
    body = ("<h1>Образы и задания пула</h1>"
            "<table><tr><th>Ref</th><th>Тип</th><th>№ задания</th></tr>"
            f"{rows or '<tr><td colspan=3>пусто</td></tr>'}</table>")
    return _page("Образы — hashpass", body)


_ROLES = ("student", "author", "admin")


def _user_row(p: dict) -> str:
    user = escape(str(p["user"]))
    role = str(p.get("role", "student"))
    opts = "".join(f"<option value='{r}'{' selected' if r == role else ''}>{r}</option>"
                   for r in _ROLES)
    role_form = (f"<form class='inline row' method='post' action='/web/users/role'>"
                 f"<input type='hidden' name='user' value='{user}'>"
                 f"<select name='role'>{opts}</select>"
                 f"<button class='sm' type='submit'>OK</button></form>")
    reset_form = (f"<form class='inline' method='post' action='/web/users/reset'>"
                  f"<input type='hidden' name='user' value='{user}'>"
                  f"<button class='sm ghost' type='submit'>ссылка сброса</button></form>")
    return (f"<tr><td class='mono'>{user}</td><td>{escape(str(p.get('group', '')))}</td>"
            f"<td><span class='pill {escape(role)}'>{escape(role)}</span></td>"
            f"<td>{escape(str(p.get('comment', '')))}</td>"
            f"<td>{role_form}</td><td>{reset_form}</td></tr>")


def render_users(profiles: list[dict], *, registration_open: bool) -> str:
    """User management: per-user role change + reset link, and the registration toggle."""
    reg = "открыта" if registration_open else "закрыта"
    toggle_to = "false" if registration_open else "true"
    toggle_label = "Закрыть регистрацию" if registration_open else "Открыть регистрацию"
    rows = "".join(_user_row(p) for p in profiles)
    body = ("<h1>Пользователи</h1>"
            f"<div class='card'><div class='row' style='justify-content:space-between'>"
            f"<span>Самостоятельная регистрация: <b>{reg}</b></span>"
            f"<form class='inline' method='post' action='/web/users/registration'>"
            f"<input type='hidden' name='open' value='{toggle_to}'>"
            f"<button class='sm' type='submit'>{toggle_label}</button></form></div></div>"
            "<h2>Все пользователи</h2>"
            "<table class='wide'><tr><th>Логин</th><th>Группа</th><th>Роль</th><th>Комментарий</th>"
            "<th>Изменить роль</th><th>Пароль</th></tr>"
            f"{rows or '<tr><td colspan=6 class=dim>нет пользователей</td></tr>'}</table>")
    return _page("Пользователи — hashpass", body)
