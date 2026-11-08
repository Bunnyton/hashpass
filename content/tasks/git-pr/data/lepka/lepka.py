#!/usr/bin/env python3
"""Лепка -- учебный git-хостинг для заданий про pull request.

Показывает голые репозитории из /etc/lepka.json в браузере (carbonyl в консоли или обычный
браузер снаружи): ветки, коммиты, pull request'ы с обсуждением, ревью, комментариями к строкам,
проверками (CI = команда из конфига на коде ветки) и кнопкой слияния (обычное или squash).
Сценарий задания -- коллеги-боты -- живёт в отдельном модуле (config "bot"): он получает
события (opened, updated, review, comment, merged) и может писать от их имени.

Запуск: lepka.py serve [порт] | lepka.py sync <репо> (из post-receive) | lepka.py dump <репо>.
Только стандартная библиотека Python и git.
"""
import fcntl
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONFIG = os.environ.get("LEPKA_CONFIG", "/etc/lepka.json")
DATA = os.environ.get("LEPKA_DATA", "/var/lib/lepka")
LOCK = threading.RLock()


def cfg():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def user_name(login):
    return cfg().get("users", {}).get(login, login)


def me():
    # LEPKA_ME -- act as a colleague while a task sets the scene (open/merge from the CLI)
    return os.environ.get("LEPKA_ME") or cfg().get("me", "student")


# ---------------------------------------------------------------- git

def git(repo, *args, check=True, env=None, input=None):
    path = cfg()["repos"][repo]["path"]
    e = dict(os.environ, GIT_DIR=path, LEPKA_INTERNAL="1")
    if env:
        e.update(env)
    r = subprocess.run(["git", "-c", "safe.directory=*", *args], capture_output=True,
                       text=True, env=e, input=input)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r


def branches(repo):
    out = git(repo, "for-each-ref", "--format=%(refname:short) %(objectname)",
              "refs/heads").stdout.split("\n")
    return dict(line.split(" ", 1) for line in out if line)


def sha_of(repo, ref):
    r = git(repo, "rev-parse", "-q", "--verify", f"refs/heads/{ref}^{{commit}}", check=False)
    return r.stdout.strip() or None


def commits(repo, base, head):
    out = git(repo, "log", "--reverse", "--format=%h%x1f%an%x1f%s", f"{base}..{head}",
              check=False).stdout
    return [line.split("\x1f") for line in out.split("\n") if line]


def mergeable(repo, base_sha, head_sha):
    """(True, []) or (False, [conflicted files])."""
    r = git(repo, "merge-tree", "--write-tree", "--name-only", base_sha, head_sha, check=False)
    if r.returncode == 0:
        return True, []
    lines = r.stdout.split("\n")[1:]
    files = []
    for line in lines:
        if not line.strip():
            break
        files.append(line.strip())
    return False, files


# ---------------------------------------------------------------- state

def _path(repo):
    return os.path.join(DATA, f"{repo}.json")


class Store:
    """prs.json of one repo under a file lock (the web server and post-receive both write)."""

    def __init__(self, repo):
        self.repo = repo

    def __enter__(self):
        os.makedirs(DATA, exist_ok=True)
        self.f = open(_path(self.repo) + ".lock", "a+")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        try:
            with open(_path(self.repo), encoding="utf-8") as f:
                self.d = json.load(f)
        except FileNotFoundError:
            self.d = {"next": 1, "prs": []}
        return self.d

    def __exit__(self, *exc):
        if exc[0] is None:
            tmp = _path(self.repo) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, _path(self.repo))
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def find(d, n):
    for pr in d["prs"]:
        if pr["n"] == n:
            return pr
    return None


def now():
    return time.strftime("%d.%m %H:%M")


# ---------------------------------------------------------------- CI

def run_ci(repo, sha):
    cmd = cfg()["repos"][repo].get("ci")
    if not cmd:
        return {"status": "none", "output": ""}
    tmp = tempfile.mkdtemp(prefix="lepka-ci-")
    try:
        path = cfg()["repos"][repo]["path"]
        tar = subprocess.run(["git", "-c", "safe.directory=*", "--git-dir", path, "archive",
                              "--format=tar", sha], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", tmp], input=tar.stdout, check=True)
        try:
            r = subprocess.run(["sh", "-c", cmd], cwd=tmp, capture_output=True, text=True,
                               timeout=60)
            out = (r.stdout + r.stderr).strip().split("\n")[-30:]
            return {"status": "ok" if r.returncode == 0 else "fail", "output": "\n".join(out)}
        except subprocess.TimeoutExpired:
            return {"status": "fail", "output": "проверка не уложилась в 60 секунд"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- bot

def load_bot(repo):
    path = cfg()["repos"][repo].get("bot")
    if not path or not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location(f"lepka_bot_{repo}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Api:
    """What a bot may do -- always inside the caller's Store."""

    def __init__(self, repo, d):
        self.repo, self.d = repo, d

    def say(self, pr, author, body, path=None, line=None):
        pr["timeline"].append({"kind": "comment", "author": author, "body": body,
                               "path": path, "line": line, "time": now()})

    def review(self, pr, author, state, body):
        pr["reviews"][author] = {"state": state, "sha": pr["head_sha"]}
        pr["timeline"].append({"kind": "review", "author": author, "state": state,
                               "body": body, "time": now()})

    def git(self, *args, **kw):
        return git(self.repo, *args, **kw)

    def pushed(self, pr, author):
        """A colleague pushed to the PR branch (after commit_file): record it, run checks."""
        head = sha_of(self.repo, pr["head"])
        n = len(commits(self.repo, pr["head_sha"], head))
        pr["head_sha"] = head
        pr["timeline"].append({"kind": "push", "author": author, "time": now(),
                               "body": f"добавил коммитов: {n}"})
        pr["checks"][head] = run_ci(self.repo, head)

    def commit_file(self, branch, author, email, message, path, content, date=None):
        """One new commit on <branch>: <path> replaced with <content> (plumbing, no worktree)."""
        parent = sha_of(self.repo, branch)
        env = {"GIT_INDEX_FILE": tempfile.mktemp(prefix="lepka-idx-")}
        try:
            git(self.repo, "read-tree", parent, env=env)
            blob = git(self.repo, "hash-object", "-w", "--stdin", input=content).stdout.strip()
            git(self.repo, "update-index", "--add", "--cacheinfo", f"100755,{blob},{path}"
                if path.endswith(".sh") else f"100644,{blob},{path}", env=env)
            tree = git(self.repo, "write-tree", env=env).stdout.strip()
        finally:
            try:
                os.unlink(env["GIT_INDEX_FILE"])
            except FileNotFoundError:
                pass
        ident = {"GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": email,
                 "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": email}
        if date:
            ident.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        c = git(self.repo, "commit-tree", tree, "-p", parent, "-m", message,
                env=ident).stdout.strip()
        git(self.repo, "update-ref", f"refs/heads/{branch}", c, parent)
        return c


def fire(repo, d, pr, event, **kw):
    bot = load_bot(repo)
    if bot and hasattr(bot, "on_event"):
        bot.on_event(event, pr, Api(repo, d), **kw)


def can_merge(repo, d, pr):
    """(ok, reasons, conflicted files)."""
    reasons = []
    base_sha = sha_of(repo, pr["base"])
    head_sha = sha_of(repo, pr["head"])
    if not head_sha:
        return False, ["ветки больше нет на сервере"], []
    ok, files = mergeable(repo, base_sha, head_sha)
    if not ok:
        reasons.append("конфликт с " + pr["base"])
    ci = pr["checks"].get(head_sha)
    if ci and ci["status"] == "fail":
        reasons.append("проверки не прошли")
    if ci and ci["status"] == "running":
        reasons.append("проверки ещё идут")
    need = cfg()["repos"][repo].get("review_by")
    if need:
        rv = pr["reviews"].get(need)
        if not rv or rv["state"] != "approved":
            reasons.append(f"нужно одобрение: {user_name(need)}")
    for who, rv in pr["reviews"].items():
        if rv["state"] == "changes" and who != need:
            reasons.append(f"{user_name(who)} просит изменений")
    bot = load_bot(repo)
    if bot and hasattr(bot, "merge_blockers"):
        reasons += bot.merge_blockers(pr, Api(repo, d))
    return not reasons, reasons, files


# ---------------------------------------------------------------- sync

def sync(repo, d):
    """Catch up with the bare repository: new pushes to PR branches -> CI + 'updated'."""
    for pr in d["prs"]:
        if pr["state"] != "open":
            continue
        head = sha_of(repo, pr["head"])
        if head and head != pr["head_sha"]:
            old = pr["head_sha"]
            pr["head_sha"] = head
            n = len(commits(repo, old, head)) if old else 0
            pr["timeline"].append({"kind": "push", "author": me(), "time": now(),
                                   "body": f"добавил коммитов: {n}" if n else
                                   "ветка перезаписана (force push)"})
            pr["checks"][head] = run_ci(repo, head)
            fire(repo, d, pr, "updated")
        elif head and head not in pr["checks"]:
            pr["checks"][head] = run_ci(repo, head)


def sync_repo(repo):
    with Store(repo) as d:
        sync(repo, d)


def open_pr(repo, d, head, base, title, body, author=None):
    n = d["next"]
    d["next"] += 1
    sha = sha_of(repo, head)
    pr = {"n": n, "title": title, "body": body, "head": head, "base": base,
          "author": author or me(), "state": "open", "created": now(), "head_sha": sha,
          "reviews": {}, "checks": {}, "timeline": [], "merged_sha": None, "method": None}
    d["prs"].append(pr)
    pr["checks"][sha] = run_ci(repo, sha)
    fire(repo, d, pr, "opened")
    return pr


def merge_pr(repo, d, pr, method, delete_branch):
    ok, reasons, _ = can_merge(repo, d, pr)
    if not ok:
        raise RuntimeError("Слить нельзя: " + "; ".join(reasons))
    bot = load_bot(repo)
    if bot and hasattr(bot, "check_method"):
        why = bot.check_method(pr, method)
        if why:
            raise RuntimeError(why)
    path = cfg()["repos"][repo]["path"]
    tmp = tempfile.mkdtemp(prefix="lepka-merge-")
    who = user_name(me())
    env = dict(os.environ, LEPKA_INTERNAL="1", GIT_AUTHOR_NAME=who,
               GIT_AUTHOR_EMAIL=f"{me()}@hashpass.local", GIT_COMMITTER_NAME=who,
               GIT_COMMITTER_EMAIL=f"{me()}@hashpass.local")

    def g(*a):
        r = subprocess.run(["git", "-c", "safe.directory=*", *a], cwd=tmp + "/w",
                           capture_output=True, text=True, env=env)
        if r.returncode:
            raise RuntimeError(r.stderr.strip())
        return r.stdout
    try:
        subprocess.run(["git", "-c", "safe.directory=*", "clone", "-q", "-b", pr["base"], path,
                        tmp + "/w"], check=True, env=env, capture_output=True)
        g("fetch", "-q", "origin", pr["head"])
        if method == "squash":
            g("merge", "-q", "--squash", "FETCH_HEAD")
            a = git(repo, "log", "-1", "--format=%an%x1f%ae", pr["head_sha"]).stdout.strip()
            an, ae = a.split("\x1f")
            g("-c", f"user.name={an}", "-c", f"user.email={ae}", "commit", "-q",
              f"--author={an} <{ae}>", "-m", f"{pr['title']} (#{pr['n']})")
        else:
            g("merge", "-q", "--no-ff", "-m",
              f"Слить PR #{pr['n']}: {pr['title']}\n\nиз ветки {pr['head']}", "FETCH_HEAD")
        g("push", "-q", "origin", pr["base"])
        merged = g("rev-parse", "HEAD").strip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    pr["state"] = "merged"
    pr["merged_sha"] = merged
    pr["method"] = method
    pr["timeline"].append({"kind": "merged", "author": me(), "time": now(),
                           "body": ("squash: один коммит " if method == "squash" else
                                    "коммит слияния ") + merged[:7] + f" в {pr['base']}"})
    if delete_branch:
        git(repo, "update-ref", "-d", f"refs/heads/{pr['head']}", check=False)
        pr["timeline"].append({"kind": "event", "author": me(), "time": now(),
                               "body": f"ветка {pr['head']} удалена"})
    fire(repo, d, pr, "merged")


# ---------------------------------------------------------------- HTML

CSS = """
body{font-family:'DejaVu Sans',sans-serif;margin:0;background:#f4f1ea;color:#1f1d1a;font-size:17px}
header{background:#3b2f2a;color:#f8efe2;padding:10px 20px;display:flex;gap:20px;align-items:center}
header a{color:#f8efe2;text-decoration:none}
header .logo{font-weight:bold;font-size:20px}
header .who{margin-left:auto;opacity:.85}
main{max-width:1000px;margin:0 auto;padding:16px 20px 60px}
a{color:#7a3b12}
h1{font-size:24px;margin:8px 0 12px}
h2{font-size:19px;margin:22px 0 8px}
.box{background:#fffdf8;border:1px solid #d8cfc0;border-radius:6px;padding:12px 14px;margin:10px 0}
.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:15px;font-weight:bold}
.open{background:#2f7d32;color:#fff}.merged{background:#6a3d9a;color:#fff}.closed{background:#9a3d3d;color:#fff}
.ok{color:#2f7d32;font-weight:bold}.fail{color:#b3261e;font-weight:bold}.warn{color:#9a6a00;font-weight:bold}
.muted{color:#6b6257}
pre{background:#272320;color:#f2ece3;padding:10px;border-radius:6px;overflow-x:auto;font-size:15px}
table.diff{border-collapse:collapse;width:100%;font-family:'DejaVu Sans Mono',monospace;font-size:14px}
table.diff td{padding:0 6px;white-space:pre-wrap;vertical-align:top}
table.diff td.n{color:#8b8173;text-align:right;width:3em;user-select:none}
tr.add{background:#e3f4df}tr.del{background:#fbe3e1}tr.hunk{background:#ece6da;color:#6b6257}
tr.file td{background:#3b2f2a;color:#f8efe2;font-weight:bold;padding:4px 8px}
.c{font-family:'DejaVu Sans',sans-serif;background:#fff6d6;border-left:4px solid #e0a800;padding:6px 10px;margin:4px 0;white-space:normal}
input[type=text],textarea,select{font:inherit;width:100%;box-sizing:border-box;padding:6px;border:1px solid #b9ad9a;border-radius:4px;background:#fff}
textarea{min-height:90px}
button{font:inherit;padding:7px 16px;border-radius:5px;border:1px solid #5d4a40;background:#5d4a40;color:#fff;cursor:pointer}
button.green{background:#2f7d32;border-color:#2f7d32}
button:disabled{background:#bdb3a5;border-color:#bdb3a5;cursor:not-allowed}
.ev{border-left:3px solid #d8cfc0;margin-left:10px;padding:2px 0 2px 14px}
.flash{background:#fbe3e1;border:1px solid #b3261e;padding:8px 12px;border-radius:6px}
"""


def esc(s):
    return html.escape(str(s or ""))


def page(title, body):
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>{esc(title)} · Лепка</title><style>{CSS}</style></head><body>
<header><a class="logo" href="/">🥟 Лепка</a><span class="muted">учебный git-хостинг</span>
<span class="who">вы: {esc(user_name(me()))} ({esc(me())})</span></header>
<main>{body}</main></body></html>"""


def badge(state):
    return {"open": '<span class="badge open">открыт</span>',
            "merged": '<span class="badge merged">слит</span>',
            "closed": '<span class="badge closed">закрыт</span>'}[state]


def ci_html(ci):
    if not ci or ci["status"] == "none":
        return '<span class="muted">проверок нет</span>'
    if ci["status"] == "ok":
        return '<span class="ok">✓ проверки прошли</span>'
    if ci["status"] == "running":
        return '<span class="warn">… проверки идут</span>'
    return '<span class="fail">✗ проверки не прошли</span>'


def render_diff(repo, pr, base_sha, head_sha):
    mb = git(repo, "merge-base", base_sha, head_sha, check=False).stdout.strip() or base_sha
    raw = git(repo, "diff", "--no-color", "-U3", mb, head_sha).stdout
    notes = {}
    for ev in pr["timeline"]:
        if ev["kind"] == "comment" and ev.get("path"):
            notes.setdefault((ev["path"], ev["line"]), []).append(ev)
    rows, path, new_ln, old_ln = [], None, 0, 0
    for line in raw.split("\n"):
        if line.startswith("diff --git"):
            continue
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
            rows.append(f'<tr class="file"><td colspan="3">{esc(path)}</td></tr>')
            continue
        if line.startswith(("--- ", "index ", "new file", "deleted file", "similarity",
                            "rename ", "old mode", "new mode")):
            continue
        m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)", line)
        if m:
            old_ln, new_ln = int(m.group(1)), int(m.group(2))
            rows.append(f'<tr class="hunk"><td class="n">…</td><td class="n">…</td>'
                        f'<td>{esc(m.group(3).strip())}</td></tr>')
            continue
        if line.startswith("+"):
            ln = new_ln
            link = (f'<a href="/{repo}/pull/{pr["n"]}/comment?path={urllib.parse.quote(path)}'
                    f'&line={ln}" title="комментарий к строке">💬</a>')
            rows.append(f'<tr class="add"><td class="n"></td><td class="n">{ln} {link}</td>'
                        f'<td>{esc(line)}</td></tr>')
            new_ln += 1
        elif line.startswith("-"):
            rows.append(f'<tr class="del"><td class="n">{old_ln}</td><td class="n"></td>'
                        f'<td>{esc(line)}</td></tr>')
            old_ln += 1
            continue
        elif line.startswith(" "):
            ln = new_ln
            link = (f'<a href="/{repo}/pull/{pr["n"]}/comment?path={urllib.parse.quote(path)}'
                    f'&line={ln}" title="комментарий к строке">💬</a>')
            rows.append(f'<tr><td class="n">{old_ln}</td><td class="n">{ln} {link}</td>'
                        f'<td>{esc(line)}</td></tr>')
            new_ln += 1
            old_ln += 1
        else:
            continue
        for ev in notes.get((path, ln), []):
            rows.append(f'<tr><td></td><td></td><td><div class="c"><b>{esc(user_name(ev["author"]))}'
                        f'</b> <span class="muted">{esc(ev["time"])}</span><br>{esc(ev["body"])}'
                        f'</div></td></tr>')
    if not rows:
        return '<p class="muted">Изменений нет.</p>'
    return '<table class="diff">' + "".join(rows) + "</table>"


def view_index():
    items = "".join(f'<li><a href="/{r}"><b>{esc(r)}</b></a> — '
                    f'<span class="muted">{esc(v.get("about", ""))}</span></li>'
                    for r, v in cfg()["repos"].items())
    return page("Репозитории", f"<h1>Репозитории</h1><ul>{items}</ul>")


def view_repo(repo, d):
    br = branches(repo)
    rows = "".join(f'<li><code>{esc(b)}</code> <span class="muted">{s[:7]}</span>'
                   + (f' — <a href="/{repo}/compare?head={urllib.parse.quote(b)}">'
                      f'открыть pull request</a>' if b != "main" else " (основная)")
                   + "</li>" for b, s in sorted(br.items()))
    opened = [p for p in d["prs"] if p["state"] == "open"]
    log = git(repo, "log", "--format=%h%x1f%an%x1f%s", "-15", "main", check=False).stdout
    logs = "".join(f'<li><code>{esc(h)}</code> {esc(s)} <span class="muted">— {esc(a)}</span></li>'
                   for h, a, s in (line.split("\x1f") for line in log.split("\n") if line))
    path = cfg()["repos"][repo]["path"]
    return page(repo, f"""<h1>{esc(repo)}</h1>
<p class="muted">Адрес для git clone / git remote: <code>{esc(path)}</code></p>
<div class="row"><a href="/{repo}/pulls"><b>Pull requests</b></a>
<span class="muted">открытых: {len(opened)}</span>
<a href="/{repo}/compare">＋ Новый pull request</a></div>
<h2>Ветки</h2><ul>{rows}</ul><h2>Последние коммиты в main</h2><ul>{logs}</ul>""")


def view_pulls(repo, d):
    rows = "".join(f'<div class="box row">{badge(p["state"])} <a href="/{repo}/pull/{p["n"]}">'
                   f'<b>#{p["n"]} {esc(p["title"])}</b></a> <span class="muted">'
                   f'{esc(p["head"])} → {esc(p["base"])} · {esc(user_name(p["author"]))} · '
                   f'{esc(p["created"])}</span></div>' for p in reversed(d["prs"]))
    return page("Pull requests", f"""<h1><a href="/{repo}">{esc(repo)}</a> · Pull requests</h1>
<p><a href="/{repo}/compare">＋ Новый pull request</a></p>{rows or '<p class="muted">Пока ни одного.</p>'}""")


def view_compare(repo, d, q, error=""):
    br = branches(repo)
    head = q.get("head", "")
    opts = "".join(f'<option value="{esc(b)}"{" selected" if b == head else ""}>{esc(b)}</option>'
                   for b in sorted(br) if b != "main")
    if not opts:
        return page("Новый pull request", f"""<h1>Новый pull request</h1>
<div class="flash">На сервере нет ни одной ветки, кроме main. Сначала отправь свою ветку:
<code>git push -u origin имя-ветки</code></div>""")
    preview = ""
    if head in br:
        cs = commits(repo, br.get("main", ""), br[head])
        preview = "<h2>Коммиты в ветке</h2><ul>" + "".join(
            f"<li><code>{esc(h)}</code> {esc(s)}</li>" for h, a, s in cs) + "</ul>" if cs else \
            '<p class="warn">В этой ветке нет коммитов, которых нет в main.</p>'
    err = f'<div class="flash">{esc(error)}</div>' if error else ""
    return page("Новый pull request", f"""<h1><a href="/{repo}">{esc(repo)}</a> · Новый pull request</h1>{err}
<form method="get" action="/{repo}/compare" class="box row">
<label>Влить ветку <select name="head">{opts}</select></label> → <b>main</b>
<button type="submit">Показать</button></form>{preview}
<form method="post" action="/{repo}/compare" class="box">
<input type="hidden" name="head" value="{esc(head)}">
<p><label>Заголовок<br><input type="text" name="title" placeholder="Что делает этот PR"></label></p>
<p><label>Описание<br><textarea name="body" placeholder="Зачем и что поменялось"></textarea></label></p>
<button class="green" type="submit" {"" if head in br else "disabled"}>Создать pull request</button>
{"" if head in br else '<span class="muted"> — сначала выбери ветку и нажми «Показать»</span>'}
</form>""")


def view_pr(repo, d, pr, error=""):
    base_sha, head_sha = sha_of(repo, pr["base"]), sha_of(repo, pr["head"]) or pr["head_sha"]
    cs = commits(repo, base_sha if pr["state"] == "open" else pr["merged_sha"] + "^1",
                 head_sha) if pr["state"] == "open" else []
    tl = []
    for ev in pr["timeline"]:
        who = esc(user_name(ev["author"]))
        if ev["kind"] == "review":
            st = {"approved": '<span class="ok">одобрил(а) ✓</span>',
                  "changes": '<span class="fail">просит изменений ✗</span>',
                  "comment": "оставил(а) отзыв"}[ev["state"]]
            tl.append(f'<div class="box"><b>{who}</b> {st} <span class="muted">{esc(ev["time"])}'
                      f'</span><br>{esc(ev["body"])}</div>')
        elif ev["kind"] == "comment":
            where = (f' <span class="muted">к строке {esc(ev["path"])}:{ev["line"]}</span>'
                     if ev.get("path") else "")
            tl.append(f'<div class="box"><b>{who}</b>{where} <span class="muted">{esc(ev["time"])}'
                      f'</span><br>{esc(ev["body"])}</div>')
        else:
            tl.append(f'<div class="ev muted">{who}: {esc(ev["body"])} · {esc(ev["time"])}</div>')
    ci = pr["checks"].get(head_sha)
    ci_out = f'<pre>{esc(ci["output"])}</pre>' if ci and ci.get("output") else ""
    merge = ""
    if pr["state"] == "open":
        ok, reasons, files = can_merge(repo, d, pr)
        conflict = (f'<p class="fail">Конфликт с {esc(pr["base"])} в файлах: '
                    f'{esc(", ".join(files))}. Сайт его не разрешит — обнови ветку у себя и '
                    f'отправь снова.</p>') if files else ""
        methods = cfg()["repos"][repo].get("merge", ["merge", "squash"])
        radios = "".join(
            f'<label><input type="radio" name="method" value="{m}"{" checked" if i == 0 else ""}> '
            f'{"коммит слияния" if m == "merge" else "squash — один коммит"}</label> '
            for i, m in enumerate(methods))
        merge = f"""<div class="box"><h2 style="margin-top:0">Слияние</h2>
{conflict}<p>{"<span class='ok'>Можно сливать.</span>" if ok else
                "<span class='fail'>Нельзя слить: " + esc("; ".join(reasons)) + ".</span>"}</p>
<form method="post" action="/{repo}/pull/{pr['n']}/merge"><p>{radios}</p>
<p><label><input type="checkbox" name="delete" value="1" checked> удалить ветку
{esc(pr['head'])} после слияния</label></p>
<button class="green" type="submit" {"" if ok else "disabled"}>Слить pull request</button></form></div>
<div class="box"><h2 style="margin-top:0">Ревью и комментарий</h2>
<form method="post" action="/{repo}/pull/{pr['n']}/review">
<p><textarea name="body" placeholder="Комментарий"></textarea></p>
<p><label><input type="radio" name="state" value="comment" checked> просто комментарий</label>
<label><input type="radio" name="state" value="approved"> одобрить</label>
<label><input type="radio" name="state" value="changes"> запросить изменения</label></p>
<button type="submit">Отправить</button></form>
<p class="muted">Комментарий к конкретной строке — значок 💬 у строки в изменениях ниже.</p></div>"""
    err = f'<div class="flash">{esc(error)}</div>' if error else ""
    commits_html = "".join(f"<li><code>{esc(h)}</code> {esc(s)} <span class='muted'>— {esc(a)}"
                           f"</span></li>" for h, a, s in cs)
    diff = render_diff(repo, pr, base_sha, head_sha) if pr["state"] == "open" else \
        render_diff(repo, pr, pr["merged_sha"] + "^1", pr["merged_sha"])
    return page(f"#{pr['n']} {pr['title']}", f"""{err}
<h1><a href="/{repo}/pulls">{esc(repo)}</a> · {esc(pr['title'])} <span class="muted">#{pr['n']}</span></h1>
<div class="row">{badge(pr['state'])} <span><b>{esc(user_name(pr['author']))}</b> {"хочет влить" if pr['state'] == 'open' else "влил(а)"}
<code>{esc(pr['head'])}</code> в <code>{esc(pr['base'])}</code></span>
{ci_html(ci) if pr['state'] == 'open' else ''}</div>
<div class="box">{esc(pr['body']) or '<span class="muted">Без описания.</span>'}</div>
{ci_out if pr['state'] == 'open' and ci and ci['status'] == 'fail' else ''}
<h2>Обсуждение</h2>{''.join(tl) or '<p class="muted">Пока тихо.</p>'}
{merge}
{'<h2>Коммиты</h2><ul>' + commits_html + '</ul>' if commits_html else ''}
<h2>Изменения</h2>{diff}""")


def view_comment(repo, pr, path, line):
    src = git(repo, "show", f"{pr['head_sha']}:{path}", check=False).stdout.split("\n")
    text = src[line - 1] if 0 < line <= len(src) else ""
    return page("Комментарий к строке", f"""<h1><a href="/{repo}/pull/{pr['n']}">#{pr['n']}
{esc(pr['title'])}</a> · комментарий к строке</h1>
<div class="box"><b>{esc(path)}:{line}</b><pre>{esc(text)}</pre>
<form method="post" action="/{repo}/pull/{pr['n']}/comment">
<input type="hidden" name="path" value="{esc(path)}"><input type="hidden" name="line" value="{line}">
<p><textarea name="body" placeholder="Что не так в этой строке?"></textarea></p>
<button type="submit">Оставить комментарий</button></form></div>""")


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, code=200):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, to):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def route(self):
        u = urllib.parse.urlsplit(self.path)
        parts = [urllib.parse.unquote(p) for p in u.path.strip("/").split("/") if p]
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        return parts, q

    def form(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8")
        return {k: v[-1] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}

    def do_GET(self):
        parts, q = self.route()
        try:
            with LOCK:
                if not parts:
                    return self.send(view_index())
                repo = parts[0]
                if repo not in cfg()["repos"]:
                    return self.send(page("Нет такого", "<h1>Нет такой страницы</h1>"), 404)
                with Store(repo) as d:
                    sync(repo, d)
                    if len(parts) == 1:
                        return self.send(view_repo(repo, d))
                    if parts[1] == "pulls":
                        return self.send(view_pulls(repo, d))
                    if parts[1] == "compare":
                        return self.send(view_compare(repo, d, q))
                    if parts[1] == "pull" and len(parts) >= 3 and parts[2].isdigit():
                        pr = find(d, int(parts[2]))
                        if pr and len(parts) == 4 and parts[3] == "comment":
                            return self.send(view_comment(repo, pr, q.get("path", ""),
                                                          int(q.get("line", "0") or 0)))
                        if pr:
                            return self.send(view_pr(repo, d, pr))
            self.send(page("Нет такого", "<h1>Нет такой страницы</h1>"), 404)
        except Exception as e:  # noqa: BLE001 -- show, don't die
            self.send(page("Ошибка", f"<h1>Ошибка</h1><pre>{esc(e)}</pre>"), 500)

    def do_POST(self):
        parts, q = self.route()
        f = self.form()
        try:
            with LOCK:
                repo = parts[0] if parts else ""
                if repo not in cfg()["repos"]:
                    return self.send(page("Нет такого", "<h1>Нет такой страницы</h1>"), 404)
                with Store(repo) as d:
                    sync(repo, d)
                    if parts[1:] == ["compare"]:
                        head, title = f.get("head", ""), f.get("title", "").strip()
                        if head not in branches(repo):
                            return self.send(view_compare(repo, d, f, "Выбери ветку."))
                        if not title:
                            return self.send(view_compare(repo, d, f,
                                                          "Напиши заголовок: что делает этот PR."))
                        if any(p["head"] == head and p["state"] == "open" for p in d["prs"]):
                            return self.send(view_compare(repo, d, f,
                                                          "Для этой ветки pull request уже открыт."))
                        if not commits(repo, sha_of(repo, "main"), sha_of(repo, head)):
                            return self.send(view_compare(repo, d, f,
                                                          "В ветке нет новых коммитов — сливать нечего."))
                        pr = open_pr(repo, d, head, "main", title, f.get("body", "").strip())
                        return self.redirect(f"/{repo}/pull/{pr['n']}")
                    pr = find(d, int(parts[2])) if len(parts) >= 4 and parts[2].isdigit() else None
                    if not pr:
                        return self.send(page("Нет такого", "<h1>Нет такой страницы</h1>"), 404)
                    act = parts[3]
                    if act == "merge":
                        try:
                            merge_pr(repo, d, pr, f.get("method", "merge"), f.get("delete") == "1")
                        except RuntimeError as e:
                            return self.send(view_pr(repo, d, pr, str(e)))
                    elif act == "review":
                        body, state = f.get("body", "").strip(), f.get("state", "comment")
                        if state == "comment" and not body:
                            return self.send(view_pr(repo, d, pr, "Пустой комментарий."))
                        if state == "comment":
                            Api(repo, d).say(pr, me(), body)
                            fire(repo, d, pr, "comment", path=None, line=None, body=body)
                        else:
                            Api(repo, d).review(pr, me(), state, body)
                            fire(repo, d, pr, "review", state=state, body=body)
                    elif act == "comment":
                        body = f.get("body", "").strip()
                        if not body:
                            return self.send(view_pr(repo, d, pr, "Пустой комментарий."))
                        path, line = f.get("path"), int(f.get("line", "0") or 0)
                        Api(repo, d).say(pr, me(), body, path, line)
                        fire(repo, d, pr, "comment", path=path, line=line, body=body)
                    return self.redirect(f"/{repo}/pull/{pr['n']}")
        except Exception as e:  # noqa: BLE001
            self.send(page("Ошибка", f"<h1>Ошибка</h1><pre>{esc(e)}</pre>"), 500)


def main(argv):
    if not argv or argv[0] == "serve":
        port = int(argv[1]) if len(argv) > 1 else 8930
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    elif argv[0] == "sync":
        sync_repo(argv[1])
    elif argv[0] == "dump":
        with Store(argv[1]) as d:
            sync(argv[1], d)
            print(json.dumps(d, ensure_ascii=False, indent=1))
    elif argv[0] == "open":  # open <repo> <head> <author> <title> [body] -- for task setup
        with Store(argv[1]) as d:
            pr = open_pr(argv[1], d, argv[2], "main", argv[4], argv[5] if len(argv) > 5 else "",
                         author=argv[3])
            print(pr["n"])
    elif argv[0] == "merge":  # merge <repo> <n> <merge|squash> [delete] -- what the button does
        with Store(argv[1]) as d:
            sync(argv[1], d)
            merge_pr(argv[1], d, find(d, int(argv[2])), argv[3], len(argv) > 4)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
