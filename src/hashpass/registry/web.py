"""Server-rendered web dashboard for the pool (stdlib only): front page, login, progress, users."""
from html import escape
from urllib.parse import quote

_REPO = "Bunnyton/hashpass"

_INSTALL_TEMPLATE = """\
#!/usr/bin/env bash
# hashpass __ROLE__ installer -- served by the pool at __POOL__
set -euo pipefail
POOL="__POOL__"
echo "Установка hashpass (__ROLE__); пул: $POOL"
# Preflight: everything the install needs must be present BEFORE we download anything.
missing=""
command -v python3 >/dev/null 2>&1 || missing="$missing python3"
python3 -m pip --version >/dev/null 2>&1 || missing="$missing python3-pip"
command -v git >/dev/null 2>&1 || missing="$missing git"
if [ -n "$missing" ]; then
  echo "не хватает зависимостей:$missing" >&2
  echo "установите их и повторите, напр.:  sudo apt install -y$missing" >&2
  exit 1
fi
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

_FONTS = ("https://fonts.googleapis.com/css2?"
          "family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap")

_STYLE = """
:root{color-scheme:light dark;
  --bg:#eef1f6;--surface:#ffffff;--surface2:#f4f7fb;--border:#e2e8f1;--border-strong:#d2dbe8;
  --text:#0f1b2d;--muted:#5a6b82;--faint:#8493a8;
  --accent:#1d63ed;--accent-ink:#ffffff;--accent-hi:#1550cf;--accent-soft:#e7effe;
  --ok:#0f9d58;--ok-soft:#e2f6ea;--warn:#b9760a;--warn-soft:#f9edd0;--danger:#d33a3a;--danger-soft:#fbe4e4;
  --shadow:0 1px 2px rgba(16,27,45,.06),0 1px 3px rgba(16,27,45,.05);--shadow-lg:0 6px 22px rgba(16,27,45,.12);
  --radius:12px;--radius-sm:9px;
  --font:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media(prefers-color-scheme:dark){:root{
  --bg:#0a1120;--surface:#111a2e;--surface2:#0e1626;--border:#233149;--border-strong:#2e4062;
  --text:#e7eefb;--muted:#9fb0c9;--faint:#68799a;
  --accent:#4b8bff;--accent-ink:#061127;--accent-hi:#6ba0ff;--accent-soft:#15233f;
  --ok:#31c06a;--ok-soft:#0f2c1c;--warn:#dfa23a;--warn-soft:#2e2612;--danger:#f0605f;--danger-soft:#331a1c;
  --shadow:0 1px 2px rgba(0,0,0,.45);--shadow-lg:0 8px 28px rgba(0,0,0,.55)}}
*{box-sizing:border-box}
body{font-family:var(--font);font-size:15px;line-height:1.55;margin:0;background:var(--bg);color:var(--text);
  -webkit-font-smoothing:antialiased}
a{color:var(--accent)}
.nav{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--surface) 88%,transparent);
  backdrop-filter:saturate(1.4) blur(8px);border-bottom:1px solid var(--border);
  display:flex;gap:4px;align-items:center;padding:10px 24px}
.nav .brand{display:flex;align-items:center;gap:9px;font-weight:800;letter-spacing:-.01em;margin-right:16px}
.nav .brand .logo{width:24px;height:24px;border-radius:7px;background:linear-gradient(135deg,var(--accent),#7aa8ff);
  box-shadow:inset 0 0 0 1px rgba(255,255,255,.25)}
.nav .brand b{color:var(--accent);font-weight:800}
.nav a{color:var(--muted);text-decoration:none;padding:7px 12px;border-radius:8px;font-weight:600;font-size:14px;
  transition:background .15s,color .15s}
.nav a:hover{background:var(--surface2);color:var(--text)}
.nav a.on{color:var(--accent);background:var(--accent-soft)}
.nav .sp{flex:1}
main{max-width:1120px;margin:0 auto;padding:30px 24px 72px}
h1{font-size:26px;font-weight:800;margin:.1em 0 .35em;letter-spacing:-.02em;text-wrap:balance}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--faint);margin:1.6em 0 .6em;font-weight:700}
.sub{color:var(--muted);margin:.2em 0 1.3em;max-width:65ch}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;
  box-shadow:var(--shadow);margin:0 0 14px}
.card.narrow{max-width:420px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;align-items:start}
table{border-collapse:separate;border-spacing:0;width:100%;background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow);font-variant-numeric:tabular-nums}
th,td{padding:10px 13px;text-align:left;border-bottom:1px solid var(--border)}
th{background:var(--surface2);font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--faint);font-weight:700}
tr:last-child td{border-bottom:0}
tbody tr:hover td,table tr:hover td{background:var(--surface2)}
td.c,th.c{text-align:center}
td a{text-decoration:none;font-weight:700}
.ok{color:var(--ok);font-weight:800}.no{color:var(--danger);font-weight:700}.dim{color:var(--muted)}
td.ok{color:var(--ok)}td.no{color:var(--danger)}
.pill{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:999px;background:var(--surface2);
  color:var(--muted);font-size:12px;font-weight:600;border:1px solid var(--border);line-height:1.3}
.pill.ok,.pill.open{background:var(--ok-soft);color:var(--ok);border-color:transparent}
.pill.no,.pill.closed{background:var(--danger-soft);color:var(--danger);border-color:transparent}
.pill.warn{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.pill.accent{background:var(--accent-soft);color:var(--accent);border-color:transparent}
.pill.admin{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.pill.author{background:var(--accent-soft);color:var(--accent);border-color:transparent}
label{display:block;margin-top:13px;font-size:12px;font-weight:600;color:var(--muted)}
input,select,textarea{font:inherit;width:100%;padding:9px 12px;margin-top:5px;border:1px solid var(--border-strong);
  border-radius:var(--radius-sm);background:var(--surface);color:var(--text);transition:border-color .15s,box-shadow .15s}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.btn,button{font:inherit;font-weight:600;padding:9px 16px;margin-top:12px;border:1px solid var(--accent);
  border-radius:var(--radius-sm);background:var(--accent);color:var(--accent-ink);cursor:pointer;text-decoration:none;
  display:inline-flex;align-items:center;gap:6px;transition:background .15s,border-color .15s,transform .05s}
.btn:hover,button:hover{background:var(--accent-hi);border-color:var(--accent-hi)}
.btn:active,button:active{transform:translateY(1px)}
.btn:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.btn.ghost,button.ghost{background:transparent;color:var(--text);border-color:var(--border-strong)}
.btn.ghost:hover,button.ghost:hover{background:var(--surface2);border-color:var(--border-strong)}
.btn.sm,button.sm{padding:5px 11px;margin:0;font-size:13px;border-radius:8px}
.btn.danger,button.danger{background:transparent;color:var(--danger);border-color:transparent}
.btn.danger:hover,button.danger:hover{background:var(--danger-soft)}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
form.inline{margin:0;display:inline-flex}form.inline.row{display:flex}form.inline select,form.inline input{width:auto;margin:0}
code,.mono{font-family:var(--mono);font-size:.92em}
.code{display:block;position:relative;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius-sm);
  padding:13px 15px;overflow-x:auto;font-family:var(--mono);font-size:13.5px;color:var(--text)}
.err{background:var(--danger-soft);color:var(--danger);border:1px solid transparent;border-radius:var(--radius-sm);
  padding:10px 13px;margin:10px 0;font-weight:500}
.note{background:var(--ok-soft);color:var(--ok);border-radius:var(--radius-sm);padding:10px 13px;margin:10px 0;font-weight:500}
.block{margin:0 0 16px;padding:16px 18px}
.block .row:first-child{margin-bottom:10px}
.tasklist{list-style:none;margin:8px 0 12px;padding:0;display:flex;flex-direction:column;gap:6px;min-height:20px}
.titem{display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--surface2);border:1px solid var(--border);
  border-radius:var(--radius-sm);cursor:grab}
.titem:hover{border-color:var(--border-strong)}
.titem .grip{color:var(--faint);cursor:grab;user-select:none;font-weight:700}
.titem .mono{flex:1}
.hero{max-width:760px;margin:6vh auto 0;text-align:center}
.hero h1{font-size:42px;letter-spacing:-.03em;line-height:1.08}
.hero .sub{margin:14px auto 0;font-size:17px;max-width:56ch}
.hero .cmd{margin:26px auto 20px;max-width:640px}
.cmd{display:flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:5px 6px 5px 16px;box-shadow:var(--shadow);text-align:left}
.cmd code{flex:1;font-family:var(--mono);font-size:14px;overflow-x:auto;white-space:nowrap;padding:9px 0}
.cmd .prompt{color:var(--faint);user-select:none}
.cmd button{margin:0}
.authwrap{max-width:400px;margin:7vh auto 0}
.authwrap .card{margin-top:14px}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
@media(max-width:640px){main{padding:20px 14px 56px}.nav{padding:10px 14px}h1{font-size:22px}.hero h1{font-size:30px}}
"""


_NAV = (("/web", "Прогресс"), ("/web/images", "Образы и каталог"),
        ("/web/users", "Пользователи"))


def _page(title: str, body: str, *, nav: bool = True, active: str = "") -> str:
    links = "".join(
        f"<a href='{href}'{' class=on' if href == active else ''}>{escape(label)}</a>"
        for href, label in _NAV)
    header = (f"<div class='nav'><span class='brand'><span class='logo'></span>hash<b>pass</b></span>"
              f"{links}<span class='sp'></span>"
              "<a href='/web/password'>Пароль</a><a href='/web/logout'>Выход</a></div>") if nav else ""
    return (f"<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
            f"<link rel='stylesheet' href='{_FONTS}'>"
            f"<title>{escape(title)}</title><style>{_STYLE}</style></head>"
            f"<body>{header}<main>{body}</main></body></html>")


def _field(label: str, name: str, *, kind: str = "text", extra: str = "") -> str:
    return f"<label>{escape(label)}<input name='{name}' type='{kind}' {extra}></label>"


_COPY_JS = ("<script>function hpcopy(b){var c=b.parentNode.querySelector('code');"
            "navigator.clipboard&&navigator.clipboard.writeText(c.innerText.replace(/^\\$\\s*/,''));"
            "var t=b.textContent;b.textContent='скопировано';setTimeout(function(){b.textContent=t;},1200);}"
            "</script>")


def render_front(pool_url: str) -> str:
    """Public front page: what the pool is + the one-line student install command."""
    url = escape(pool_url.rstrip("/"))
    # A self-signed HTTPS pool needs curl -k to fetch the installer (the pip step uses GitHub's
    # real cert, so it is unaffected); a plain-http pool does not.
    flags = "-fsSLk" if pool_url.startswith("https://") else "-fsSL"
    body = ("<div class='hero'><span class='pill accent'>учебный пул</span>"
            "<h1>Интерактивные задания по Linux</h1>"
            "<p class='sub'>Живая консоль Debian, автоматическая проверка каждого шага. "
            "Студент подключается одной командой:</p>"
            "<div class='cmd'><span class='prompt'>$</span>"
            f"<code>curl {flags} {url}/install.sh | bash</code>"
            "<button class='sm' onclick='hpcopy(this)' type='button'>копировать</button></div>"
            "<a class='btn' href='/web/login'>Вход для преподавателя</a></div>" + _COPY_JS)
    return _page("hashpass", body, nav=False)


def render_login(error: str = "") -> str:
    """Teacher/admin login form."""
    err = f"<div class='err'>{escape(error)}</div>" if error else ""
    body = ("<div class='authwrap'><h1>Вход преподавателя</h1>"
            f"<p class='sub'>Доступ к прогрессу и управлению.</p>{err}"
            "<form class='card' method='post' action='/web/login'>"
            + _field("Логин", "user", extra="autofocus")
            + _field("Пароль", "password", kind="password")
            + "<button type='submit'>Войти</button></form></div>")
    return _page("Вход — hashpass", body, nav=False)


_PW_HINT = "Не короче 8 символов, минимум одна буква, одна цифра и один спецсимвол."


def render_password_form(error: str = "", *, done: bool = False) -> str:
    """Change-own-password form (for a logged-in author/admin)."""
    msg = "<div class='note'>Пароль изменён.</div>" if done else ""
    err = f"<div class='err'>{escape(error)}</div>" if error else ""
    body = (f"<h1>Смена пароля</h1>{msg}{err}"
            "<form class='card' method='post' action='/web/password'>"
            + _field("Текущий пароль", "old", kind="password", extra="autofocus")
            + _field("Новый пароль", "new", kind="password")
            + _field("Повторите новый", "confirm", kind="password")
            + f"<p class='sub'>{_PW_HINT}</p>"
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
            + f"<p class='sub'>{_PW_HINT}</p>"
            + "<button type='submit'>Сохранить</button></form>")
    return _page("Восстановление — hashpass", body, nav=False)


def render_reset_link(user: str, link: str) -> str:
    """Show the admin the freshly generated reset link for a user, to send out-of-band."""
    body = (f"<h1>Ссылка для сброса пароля</h1>"
            f"<p class='sub'>Отправьте её пользователю <b>{escape(user)}</b> (действует ограниченно):</p>"
            f"<code class='code'>{escape(link)}</code>"
            "<p style='margin-top:16px'><a class='btn ghost' href='/web/users'>← к пользователям</a></p>")
    return _page("Сброс пароля — hashpass", body)


def _cell(user: str, ref: str, record: dict | None) -> str:
    status = (record or {}).get("status")
    if status not in ("passed", "failed"):
        return "<td class='c'>·</td>"
    verdict = ((record or {}).get("authenticity") or {}).get("verdict")
    href = f"/web/history?user={quote(user, safe='')}&ref={quote(ref, safe='')}"
    if status == "passed":
        mark, cls = ("✓⚠", "c no") if verdict == "pasted" else ("✓", "c ok")
    else:
        mark, cls = "✗", "c no"
    return f"<td class='{cls}'><a href='{href}' title='история'>{mark}</a></td>"


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
    head = "".join(f"<th title='{escape(str(e['ref']))}'>{e['number']}</th>" for e in entries)
    rows = []
    for p in students:
        user = str(p["user"])
        done = progress.get(user, {})
        cells = "".join(_cell(user, str(e["ref"]), done.get(str(e["ref"]))) for e in entries)
        passed = sum(1 for e in entries if (done.get(str(e["ref"])) or {}).get("status") == "passed")
        rows.append(f"<tr><td class='mono'>{escape(user)}</td>"
                    f"<td>{escape(str(p.get('group', '')))}</td>"
                    f"<td>{escape(str(p.get('comment', '')))}</td>"
                    f"<td class='c'>{passed}/{len(entries)}</td>{cells}</tr>")
    table = (f"<table><tr><th>Логин</th><th>Группа</th><th>Комментарий</th><th>Σ</th>{head}</tr>"
             f"{''.join(rows) or '<tr><td colspan=99>нет студентов</td></tr>'}</table>")
    return _page("Прогресс — hashpass", f"<h1>Прогресс студентов</h1>{picker}{table}", active="/web")


_VERDICT_RU = {"typed": "набрано вручную", "pasted": "похоже на вставку", "unknown": "нет данных"}


def render_history(user: str, ref: str, record: dict) -> str:
    """Render a student's command history for one task, with the anti-bot (typed/pasted) summary."""
    auth = record.get("authenticity") or {}
    verdict = _VERDICT_RU.get(str(auth.get("verdict", "unknown")), "нет данных")
    status = str(record.get("status", ""))
    rows = ""
    for h in record.get("history", []):
        cmd = str(h.get("command", ""))
        typing = h.get("typing")
        speed = f"{len(cmd) / typing:.0f} зн/с" if isinstance(typing, (int, float)) and typing > 0 else "—"
        flag = "<span class='pill no'>вставка</span>" if h.get("pasted") else ""
        rows += (f"<tr><td class='mono'>{escape(cmd)}</td>"
                 f"<td class='c'>{escape(speed)}</td><td>{flag}</td></tr>")
    table = (f"<table><tr><th>Команда</th><th class='c'>Скорость</th><th></th></tr>{rows}</table>"
             if rows else "<p class='sub'>История команд не записана (старый рантайм или нет данных).</p>")
    body = (f"<h1>История: {escape(user)}</h1>"
            f"<p class='sub'><span class='mono'>{escape(ref)}</span> — {escape(status)}; "
            f"антибот: <b>{escape(verdict)}</b> "
            f"(вручную {int(auth.get('typed', 0))}, вставлено {int(auth.get('pasted', 0))})</p>"
            f"{table}<p style='margin-top:16px'>"
            "<a class='btn ghost' href='/web'>← к прогрессу</a></p>")
    return _page("История — hashpass", body, active="/web")


def _fmt_size(n: object) -> str:
    size = int(n) if isinstance(n, (int, float)) else 0
    return f"{size} Б" if size < 1024 else f"{size / 1024:.0f} КБ"  # noqa: PLR2004


def _attachments_block(ref: str, files: list[dict]) -> str:
    q = quote(ref, safe="")
    rows = ""
    for f in files:
        name = str(f.get("name", ""))
        badge = " <span class='pill author'>Taskfile</span>" if f.get("taskfile") else ""
        rows += (
            f"<tr><td class='mono'>{escape(name)}{badge}</td>"
            f"<td class='c'>{_fmt_size(f.get('size'))}</td>"
            f"<td><a class='btn sm ghost' href='/web/images/file?ref={q}&name={quote(name, safe='')}'>"
            "скачать</a></td>"
            "<td><form class='inline' method='post' action='/web/images/attach-delete'>"
            f"<input type='hidden' name='ref' value='{escape(ref)}'>"
            f"<input type='hidden' name='name' value='{escape(name)}'>"
            "<button class='sm ghost' type='submit'>удалить</button></form></td></tr>")
    table = (f"<table><tr><th>Файл</th><th class='c'>Размер</th><th></th><th></th></tr>{rows}</table>"
             if files else
             "<p class='sub'>Файлов нет. Taskfile прикрепляется автоматически при <code>push</code>; "
             "можно приложить файлы вручную ниже.</p>")
    upload = ("<form class='inline row' method='post' action='/web/images/attach' "
              "enctype='multipart/form-data'>"
              f"<input type='hidden' name='ref' value='{escape(ref)}'>"
              "<input type='file' name='file' required>"
              "<button class='sm' type='submit'>Прикрепить</button></form>")
    return f"<h2>Файлы</h2>{table}{upload}"


def _task_li(entry: dict) -> str:
    ref = str(entry["ref"])
    return (f"<li class='titem' draggable='true' data-ref='{escape(ref)}'>"
            f"<span class='grip' title='перетащите'>≡</span> "
            f"<b>№{entry.get('number')}</b> <span class='mono'>{escape(ref)}</span>"
            "<form class='inline' method='post' action='/web/catalog/remove'>"
            f"<input type='hidden' name='ref' value='{escape(ref)}'>"
            "<button class='sm ghost' type='submit'>убрать</button></form></li>")


def _block_div(b: dict, task_options: str) -> str:
    bid, name, is_open = str(b["id"]), str(b["name"]), bool(b["open"])
    items = "".join(_task_li(e) for e in b.get("tasks", []))
    state = ("<span class='pill open'>открыт</span>" if is_open
             else "<span class='pill closed'>закрыт</span>")
    return (f"<div class='block card' data-block-id='{escape(bid)}'>"
            f"<div class='row'><b>{escape(name)}</b> {state}"
            "<form class='inline' method='post' action='/web/blocks/toggle'>"
            f"<input type='hidden' name='block_id' value='{escape(bid)}'>"
            f"<input type='hidden' name='open' value='{'0' if is_open else '1'}'>"
            f"<button class='sm' type='submit'>{'Закрыть' if is_open else 'Открыть'}</button></form>"
            "<form class='inline' method='post' action='/web/blocks/rename'>"
            f"<input type='hidden' name='block_id' value='{escape(bid)}'>"
            f"<input name='name' value='{escape(name)}' style='width:9em'>"
            "<button class='sm ghost' type='submit'>Переименовать</button></form>"
            "<form class='inline' method='post' action='/web/blocks/remove'>"
            f"<input type='hidden' name='block_id' value='{escape(bid)}'>"
            "<button class='sm ghost' type='submit'>Удалить блок</button></form></div>"
            f"<ul class='tasklist' data-block-id='{escape(bid)}'>{items}</ul>"
            "<form class='inline row' method='post' action='/web/catalog/add'>"
            f"<input type='hidden' name='block_id' value='{escape(bid)}'>"
            f"<select name='ref'>{task_options}</select>"
            "<button class='sm' type='submit'>Добавить задание</button></form></div>")


_DRAG_JS = """<script>
(function(){var dragged=null;
document.addEventListener('dragstart',function(e){var li=e.target.closest&&e.target.closest('.titem');if(li){dragged=li;e.dataTransfer.effectAllowed='move';}});
document.addEventListener('dragover',function(e){if(!dragged)return;var ul=e.target.closest('.tasklist');if(!ul)return;e.preventDefault();var li=e.target.closest('.titem');if(li&&li!==dragged){var r=li.getBoundingClientRect();ul.insertBefore(dragged,(e.clientY-r.top)/r.height>0.5?li.nextSibling:li);}else if(!li){ul.appendChild(dragged);}});
document.addEventListener('drop',function(e){if(!dragged)return;e.preventDefault();dragged=null;
var blocks=[].map.call(document.querySelectorAll('.block'),function(b){return {id:b.getAttribute('data-block-id'),tasks:[].map.call(b.querySelectorAll('.titem'),function(li){return li.getAttribute('data-ref');})};});
fetch('/web/catalog/layout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({blocks:blocks})}).then(function(){location.reload();});});
})();</script>"""


def _catalog_section(blocks: list[dict], task_refs: list[str]) -> str:
    options = "".join(f"<option value='{escape(r)}'>{escape(r)}</option>" for r in task_refs)
    body = "".join(_block_div(b, options) for b in blocks) or "<p class='sub'>Блоков пока нет.</p>"
    add_block = ("<form class='inline row' method='post' action='/web/blocks/add'>"
                 "<input name='name' placeholder='название блока' required>"
                 "<button class='sm' type='submit'>Добавить блок</button></form>")
    return (f"<h1>Каталог заданий</h1><p class='sub'>Задания сгруппированы по блокам; "
            "перетащите задание, чтобы изменить порядок или блок. Открытие блока открывает "
            f"все его задания студентам.</p>{add_block}<div id='cat'>{body}</div>")


def _image_card(row: dict) -> str:
    ref = str(row["ref"])
    kind = str(row.get("kind", "image"))
    kind_ru = {"task": "задание", "image": "образ"}.get(kind, kind)
    kind_pill = f"<span class='pill {'author' if kind == 'task' else ''}'>{escape(kind_ru)}</span>"
    number = row.get("number")
    where = (f" <span class='pill'>в каталоге №{number}, блок «{escape(str(row.get('block_name', '')))}»</span>"
             if number is not None else "")
    desc = str(row.get("description", ""))
    describe = ("<h2>Описание</h2>"
                "<form method='post' action='/web/images/describe'>"
                f"<input type='hidden' name='ref' value='{escape(ref)}'>"
                "<textarea name='description' rows='3' style='width:100%;font:inherit' "
                f"placeholder='описание образа'>{escape(desc)}</textarea>"
                "<button class='sm' type='submit'>Сохранить описание</button></form>")
    files = row.get("files") if isinstance(row.get("files"), list) else []
    return (f"<div class='card wide'><div class='row'><b class='mono'>{escape(ref)}</b> "
            f"{kind_pill}{where}</div>{describe}{_attachments_block(ref, files)}</div>")


def render_images(images: list[dict], blocks: list[dict]) -> str:
    """Render the catalog (blocks with drag-reorder) plus per-image cards (description + files)."""
    task_refs = [str(r["ref"]) for r in images if r.get("kind") == "task"]
    cards = "".join(_image_card(row) for row in images) or "<p class='sub'>Пул пуст.</p>"
    body = f"{_catalog_section(blocks, task_refs)}<h1>Образы</h1>{cards}{_DRAG_JS}"
    return _page("Образы — hashpass", body, active="/web/images")


_ROLES = ("student", "author", "admin")


def _user_row(p: dict, current_user: str) -> str:
    user = escape(str(p["user"]))
    role = str(p.get("role", "student"))
    is_self = str(p["user"]) == current_user
    reset_form = (f"<form class='inline' method='post' action='/web/users/reset'>"
                  f"<input type='hidden' name='user' value='{user}'>"
                  f"<button class='sm ghost' type='submit'>ссылка сброса</button></form>")
    if is_self:                                    # no self role-change / self-delete (lockout guard)
        role_cell, del_cell = "<span class='dim'>вы</span>", "<span class='dim'>—</span>"
    else:
        opts = "".join(f"<option value='{r}'{' selected' if r == role else ''}>{r}</option>"
                       for r in _ROLES)
        role_cell = (f"<form class='inline row' method='post' action='/web/users/role'>"
                     f"<input type='hidden' name='user' value='{user}'>"
                     f"<select name='role'>{opts}</select>"
                     f"<button class='sm' type='submit'>OK</button></form>")
        del_cell = (f"<form class='inline' method='post' action='/web/users/delete'>"
                    f"<input type='hidden' name='user' value='{user}'>"
                    f"<button class='sm ghost' type='submit'>удалить</button></form>")
    return (f"<tr><td class='mono'>{user}</td><td>{escape(str(p.get('group', '')))}</td>"
            f"<td><span class='pill {escape(role)}'>{escape(role)}</span></td>"
            f"<td>{escape(str(p.get('comment', '')))}</td>"
            f"<td>{role_cell}</td><td>{reset_form}</td><td>{del_cell}</td></tr>")


def render_users(profiles: list[dict], *, registration_open: bool, current_user: str = "") -> str:
    """User management: per-user role change / reset link / delete, delete-group, registration toggle."""
    reg = "открыта" if registration_open else "закрыта"
    toggle_to = "false" if registration_open else "true"
    toggle_label = "Закрыть регистрацию" if registration_open else "Открыть регистрацию"
    rows = "".join(_user_row(p, current_user) for p in profiles)
    body = ("<h1>Пользователи</h1>"
            f"<div class='card'><div class='row' style='justify-content:space-between'>"
            f"<span>Самостоятельная регистрация: <b>{reg}</b></span>"
            f"<form class='inline' method='post' action='/web/users/registration'>"
            f"<input type='hidden' name='open' value='{toggle_to}'>"
            f"<button class='sm' type='submit'>{toggle_label}</button></form></div></div>"
            "<div class='card'><form class='inline row' method='post' action='/web/users/delete-group'>"
            "<span>Удалить группу целиком:</span>"
            "<input name='group' placeholder='ИУ7-31' style='width:auto'>"
            "<button class='sm ghost' type='submit'>Удалить группу</button></form></div>"
            "<h2>Все пользователи</h2>"
            "<table class='wide'><tr><th>Логин</th><th>Группа</th><th>Роль</th><th>Комментарий</th>"
            "<th>Изменить роль</th><th>Пароль</th><th>Удалить</th></tr>"
            f"{rows or '<tr><td colspan=7 class=dim>нет пользователей</td></tr>'}</table>")
    return _page("Пользователи — hashpass", body, active="/web/users")
