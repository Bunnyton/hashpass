"""Server-rendered web dashboard for the pool (stdlib only): front page, login, progress, users."""
from html import escape

_STYLE = """
:root{color-scheme:light dark}
body{font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f7f9;color:#1a1c1f}
header{background:#1f2933;color:#fff;padding:14px 22px;display:flex;gap:18px;align-items:baseline}
header a{color:#9fd3ff;text-decoration:none} header .brand{font-weight:700;font-size:18px}
main{max-width:1100px;margin:0 auto;padding:22px}
h1{font-size:22px;margin:.2em 0 .6em} h2{font-size:17px;margin:1.4em 0 .5em}
table{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.08)}
th,td{border:1px solid #e3e6ea;padding:7px 10px;text-align:left;font-variant-numeric:tabular-nums}
th{background:#eef1f4} td.c{text-align:center}
.ok{color:#0a7d32;font-weight:700} .no{color:#b23}
.pill{display:inline-block;padding:1px 8px;border-radius:10px;background:#e3e6ea;font-size:12px}
form.card,div.card{background:#fff;border:1px solid #e3e6ea;border-radius:8px;padding:16px;max-width:420px}
input,select,button{font:inherit;padding:7px 9px;margin:4px 0;border:1px solid #c7ccd2;border-radius:6px}
button{background:#1f6feb;color:#fff;border-color:#1f6feb;cursor:pointer}
label{display:block;margin-top:8px;font-size:13px;color:#556}
code{background:#eef1f4;padding:2px 6px;border-radius:4px}
.err{color:#b23;margin:8px 0}
@media(prefers-color-scheme:dark){body{background:#0d1117;color:#e6edf3}
table,form.card,div.card{background:#161b22;border-color:#30363d} th{background:#21262d}
th,td{border-color:#30363d} .pill{background:#30363d}}
"""


def _page(title: str, body: str, *, nav: bool = True) -> str:
    header = ("<header><span class='brand'>hashpass</span>"
              "<a href='/web'>Прогресс</a><a href='/web/users'>Пользователи</a>"
              "<a href='/web/logout'>Выход</a></header>") if nav else ""
    return (f"<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{escape(title)}</title><style>{_STYLE}</style></head>"
            f"<body>{header}<main>{body}</main></body></html>")


def render_front(pool_url: str) -> str:
    """Public front page: what the pool is + the one-line student install command."""
    url = escape(pool_url.rstrip("/"))
    body = (f"<h1>hashpass — учебный пул</h1>"
            f"<p>Интерактивные задания по Linux в живой консоли. Установка студенту — одной командой:</p>"
            f"<p><code>curl -fsSL {url}/install.sh | bash</code></p>"
            f"<p><a href='/web/login'>Вход для преподавателя →</a></p>")
    return _page("hashpass", body, nav=False)


def render_login(error: str = "") -> str:
    """Teacher/admin login form."""
    err = f"<div class='err'>{escape(error)}</div>" if error else ""
    body = (f"<h1>Вход</h1>{err}"
            "<form class='card' method='post' action='/web/login'>"
            "<label>Логин<input name='user' autofocus></label>"
            "<label>Пароль<input name='password' type='password'></label>"
            "<button type='submit'>Войти</button></form>")
    return _page("Вход — hashpass", body, nav=False)


def _cell(status: str | None) -> str:
    if status == "passed":
        return "<td class='c ok'>✓</td>"
    if status == "failed":
        return "<td class='c no'>✗</td>"
    return "<td class='c'>·</td>"


def render_dashboard(profiles: list[dict], entries: list[dict],
                     progress: dict[str, dict], *, group: str | None = None) -> str:
    """Progress matrix: students (ФИО/group) × task numbers, each cell passed/failed/none."""
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
        rows.append(f"<tr><td>{escape(str(p.get('full_name') or user))}</td>"
                    f"<td>{escape(str(p.get('group', '')))}</td>"
                    f"<td class='c'>{passed}/{len(entries)}</td>{cells}</tr>")
    table = (f"<table><tr><th>Студент</th><th>Группа</th><th>Σ</th>{head}</tr>"
             f"{''.join(rows) or '<tr><td colspan=99>нет студентов</td></tr>'}</table>")
    return _page("Прогресс — hashpass", f"<h1>Прогресс студентов</h1>{picker}{table}")


def render_users(profiles: list[dict], *, registration_open: bool) -> str:
    """User management: list, grant author role, and the registration toggle."""
    reg = "открыта" if registration_open else "закрыта"
    toggle_to = "false" if registration_open else "true"
    toggle_label = "Закрыть регистрацию" if registration_open else "Открыть регистрацию"
    rows = "".join(
        f"<tr><td>{escape(str(p['user']))}</td><td>{escape(str(p.get('full_name', '')))}</td>"
        f"<td>{escape(str(p.get('group', '')))}</td><td><span class='pill'>{escape(str(p['role']))}"
        f"</span></td><td>{escape(str(p.get('comment', '')))}</td></tr>" for p in profiles)
    body = (f"<h1>Пользователи</h1>"
            f"<div class='card'><p>Регистрация: <b>{reg}</b></p>"
            f"<form method='post' action='/web/users/registration'>"
            f"<input type='hidden' name='open' value='{toggle_to}'>"
            f"<button type='submit'>{toggle_label}</button></form></div>"
            f"<h2>Выдать роль</h2>"
            f"<form class='card' method='post' action='/web/users/role'>"
            f"<label>Логин<input name='user'></label>"
            f"<label>Роль<select name='role'><option>student</option><option>author</option>"
            f"<option>admin</option></select></label><button type='submit'>Применить</button></form>"
            f"<h2>Все пользователи</h2><table><tr><th>Логин</th><th>ФИО</th><th>Группа</th>"
            f"<th>Роль</th><th>Комментарий</th></tr>{rows}</table>")
    return _page("Пользователи — hashpass", body)
