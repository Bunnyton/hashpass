#!/usr/bin/env python3
"""
Generate a task's real data files (`content/tasks/<id>/data/`) -- big enough to show the magic.

The files are committed next to the Taskfile and land in the image via `copy data/... /home/...`.
Everything is deterministic for a `--seed`, so the command that made a fixture is written in the
Taskfile as a comment and can be re-run.

    mkdata.py text OUT --kind ads --lines 300 --seed 1 --plant "СЕКРЕТ: …@0.6"
    mkdata.py text OUT --kind notes --lines 400 --seed 2 --sprinkle "TODO:" --sprinkle-count 24
    mkdata.py text OUT --kind log --lines 600 --seed 3 --sprinkle ERROR --sprinkle-count 41
    mkdata.py list OUT --items apple,banana,cherry --lines 500 --seed 4
    mkdata.py tree DIR --seed 5 --depth 6 --dirs 45 --files 160 [--empty 0.5] [--kind prose]
                  [--plant a/b/level4_alpha/] [--plant docs/key.txt=КЛЮЧ: x]
                  (no directory is left empty -- git would drop it; use `run mkdir -p` for those)
    mkdata.py stats DIR                # per-depth counts, to tune a seed
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

PROSE = [
    "Утро началось с кофе и падения сервера.", "Кот сел на клавиатуру и запушил в main.",
    "Никто не читает документацию, пока не сломается прод.", "Бэкап был. Где-то.",
    "Терминал не кусается, он просто ждёт.", "Логи молчат — значит, никто их не пишет.",
    "Пятница: деплой отменяется в пользу здравого смысла.", "Ошибка воспроизводится только у заказчика.",
    "На встрече решили назначить встречу.", "Сервер горячий, потому что работает, а не потому что сломан.",
    "Файл с именем final_final_v2 оказался не финальным.", "Права 777 — это не решение, это капитуляция.",
    "Каждый пробел в имени файла — чья-то слеза.", "Пароль admin ещё никого не защитил.",
    "Скрипт работал год, пока не наступил високосный.", "Кофемашина отвечает быстрее, чем тикет-система.",
    "Если сомневаешься — man.", "Табуляция против пробелов: перемирие не подписано.",
    "Уборщица нашла кабель, который искали три отдела.", "Мы не теряем данные, мы их прячем от себя.",
    "Сисадмин спит, а cron работает.", "Стажёр удалил tmp и освободил половину диска.",
    "Регламент лежит в папке, которую никто не открывал.", "Чем длиннее путь, тем нужнее Tab.",
    "Ошибка 404: обед не найден.", "Ничего не трогай, оно работает.", "Ребут решает, но не объясняет.",
    "Бумажный журнал пережил три миграции.", "Совет дня: сначала ls, потом rm.", "Всё шло по плану, пока план не прочитали.",
    "Кабель питания тоже часть инфраструктуры.", "Задача закрыта, проблема осталась.",
    "Чай остыл, тест прошёл.", "Мониторинг молчал, потому что был выключен.",
    "Кто последний менял конфиг, тот и дежурит.", "Файл нашёлся в корзине. Корзины нет.",
    "Сборка зелёная, настроение тоже.", "Не все папки одинаково полезны.", "Локалхост никогда не подводит.",
    "Одна команда — сто файлов. Вот это и есть магия.",
]
PRODUCTS = ["пылесос", "чайник", "курс по Linux", "гироскутер", "ковёр", "абонемент в зал",
            "телескоп", "набор отвёрток", "кресло-мешок", "ноутбук", "самокат", "мультиварка",
            "плед с рукавами", "умная лампочка", "фитнес-браслет", "робот-пылесос"]
SERVICES = ["интернет", "телефон", "парковку", "облако", "антивирус", "музыку", "доставку", "склад"]
ADS = [
    "Здесь может быть ваша реклама", "Скидка {n}% на {p} только до {d} числа!",
    "Купи {p} — получи {p2} в подарок!", "Ваш счёт за {s} ждёт оплаты. Не откладывайте.",
    "Поздравляем! Вы {n}-й посетитель, заберите {p}.", "Распродажа: {p} по цене {p2}.",
    "Напоминаем: акция на {p} заканчивается {d}-го.", "Только сегодня: {p} с доставкой за {n} минут.",
    "Оплатите {s} до {d} числа и получите бонус.", "Новинка сезона — {p}. Уже в продаже.",
    "Вернём {n}% за {p}. Условия внутри.", "Ваш {p} ждёт вас в пункте выдачи №{n}.",
]
NOTE_TOPICS = ["парсер конфигов", "кэш сессий", "ротацию логов", "миграцию базы", "новый CI",
               "права на /var/data", "таймауты в клиенте", "нейминг переменных", "документацию API",
               "бэкапы по пятницам", "мониторинг диска", "старый скрипт деплоя", "тесты на find",
               "утечку памяти в воркере", "лимиты в nginx", "сборку образа", "ретраи в очереди"]
NAMES = ["Ольгой", "Игорем", "Машей", "тимлидом", "Сашей", "заказчиком", "Димой", "админами"]
NOTES = [
    "- обсудить {t} с {who}", "встреча {d}.09: {t}, без решения", "идея: переписать {t}",
    "вопрос от {who}: когда починим {t}?", "заметка: {t} работает, не трогать",
    "bug #{n}: {t}, воспроизводится через раз", "ретро: {t} — больно, но терпимо",
    "напомнить {who} про {t}", "черновик письма про {t}", "{t}: отложено до релиза",
    "проверить {t} после обновления", "почему {t} тормозит по утрам?", "план на неделю: {t}",
]
TODO_TASKS = ["fix the leak", "rename ClassX", "delete dead code", "add tests", "rotate logs",
              "update README", "remove hardcoded path", "check permissions", "split the module",
              "ask ops about backups", "bump timeout", "write the migration", "close old tickets",
              "measure startup", "handle SIGTERM", "document the flags", "cache the lookup",
              "retry on 502", "escape the quotes", "pin the version", "clean tmp on exit",
              "review PR 418", "drop the legacy branch", "replace sleep with wait"]
HOSTS = ["web-01", "web-02", "api-03", "db-01", "cache-02", "worker-05", "edge-07"]
PROCS = ["nginx", "app", "postgres", "cron", "sshd", "systemd", "redis", "worker"]
LOG_MSGS = {
    "INFO": ["GET /api/v1/users 200 {n}ms", "POST /api/v1/orders 201 {n}ms", "connection accepted from 10.0.{n}.{n2}",
             "job {n} finished in {n2}s", "cache hit ratio {n}%", "session opened for user student",
             "rotating log, {n} MB written", "health check ok", "GET /static/app.js 304 {n}ms",
             "scheduled task {n} queued", "reloaded configuration", "listening on port 80{n2}"],
    "WARN": ["slow query ({n}ms): SELECT * FROM orders", "disk usage at {n}%", "retrying job {n} ({n2}/3)",
             "certificate expires in {n} days", "queue depth {n}", "GET /api/v1/report 429 rate limited",
             "clock skew {n}ms detected", "worker {n} restarted"],
    "ERROR": ["connection refused to db-01:5432", "job {n} failed: timeout after {n2}s",
              "GET /api/v1/users 500 {n}ms", "out of memory in worker {n}", "permission denied: /var/data/{n}.bin",
              "upstream timed out (110)", "cannot open /etc/app/{n}.conf", "segfault in worker {n2}",
              "TLS handshake failed with 10.0.{n}.{n2}", "disk full on /var/log"],
}
DIR_NAMES = ["archive", "backup", "docs", "src", "tmp", "old", "photos", "2019", "2020", "2021",
             "projects", "logs", "cache", "config", "data", "lib", "misc", "notes", "reports",
             "tests", "assets", "drafts", "vendor", "scripts", "music", "video", "inbox",
             "sent", "work", "home", "shared", "export", "import", "staging", "release"]
FILE_NAMES = ["readme", "notes", "todo", "report", "summary", "invoice", "draft", "letter", "list",
              "index", "main", "utils", "config", "backup", "photo", "song", "chapter", "log",
              "data", "memo", "plan", "budget", "recipe", "schedule", "manual", "changelog"]
EXTS = ["txt", "md", "log", "csv", "cfg", "txt", "txt"]
_WARN_SHARE = 0.15       # of log lines; the rest are INFO (ERROR only via --sprinkle)
_SUFFIX_SHARE = 0.6      # of generated names get a number/year suffix
_YEAR_SHARE = 0.5


def _fill(rnd: random.Random, tpl: str) -> str:
    return tpl.format(n=rnd.randint(2, 97), n2=rnd.randint(2, 97), d=rnd.randint(1, 28),
                      p=rnd.choice(PRODUCTS), p2=rnd.choice(PRODUCTS), s=rnd.choice(SERVICES),
                      t=rnd.choice(NOTE_TOPICS), who=rnd.choice(NAMES))


def _log_line(rnd: random.Random, level: str) -> str:
    ts = f"2026-09-{rnd.randint(1, 28):02d} {rnd.randint(0, 23):02d}:{rnd.randint(0, 59):02d}:{rnd.randint(0, 59):02d}"
    return f"{ts} {rnd.choice(HOSTS)} {rnd.choice(PROCS)}[{rnd.randint(100, 9999)}]: {level} {_fill(rnd, rnd.choice(LOG_MSGS[level]))}"


def gen_lines(kind: str, n: int, rnd: random.Random) -> list[str]:
    """`n` lines of the given kind -- never containing a sprinkle marker (ERROR / TODO)."""
    if kind == "prose":
        return [rnd.choice(PROSE) for _ in range(n)]
    if kind == "ads":
        return [_fill(rnd, rnd.choice(ADS)) for _ in range(n)]
    if kind == "notes":
        return [_fill(rnd, rnd.choice(NOTES)) for _ in range(n)]
    if kind == "log":
        return [_log_line(rnd, "WARN" if rnd.random() < _WARN_SHARE else "INFO") for _ in range(n)]
    msg = f"unknown kind {kind!r}"
    raise SystemExit(msg)


def sprinkle_line(kind: str, marker: str, rnd: random.Random) -> str:
    if kind == "log":
        return _log_line(rnd, marker)
    if kind == "notes":
        return f"{marker} {rnd.choice(TODO_TASKS)}"
    return f"{marker} {rnd.choice(PROSE)}"


def _position(spec: str, n: int) -> int:
    """`0.6` -> 60 % down the file, `137` -> that 1-based line."""
    return round(float(spec) * n) if "." in spec else int(spec) - 1


def cmd_text(a: argparse.Namespace) -> int:
    rnd = random.Random(a.seed)
    lines = gen_lines(a.kind, a.lines, rnd)
    if a.sprinkle:
        for pos in sorted(rnd.sample(range(len(lines)), a.sprinkle_count)):
            lines[pos] = sprinkle_line(a.kind, a.sprinkle, rnd)
    for plant in a.plant or []:
        text, _, where = plant.rpartition("@")
        lines.insert(_position(where, len(lines)), text)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{a.out}: {len(lines)} lines", file=sys.stderr)
    return 0


def cmd_list(a: argparse.Namespace) -> int:
    rnd = random.Random(a.seed)
    items = [i.strip() for i in a.items.split(",") if i.strip()]
    weights = [rnd.randint(1, 9) for _ in items]            # some items sell better than others
    lines = rnd.choices(items, weights=weights, k=a.lines)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{a.out}: {len(lines)} lines, {len(set(lines))} distinct", file=sys.stderr)
    return 0


def _unique(rnd: random.Random, pool: list[str], taken: set[str], ext: str | None = None) -> str:
    for _ in range(1000):
        name = rnd.choice(pool)
        if rnd.random() < _SUFFIX_SHARE:
            name += f"{rnd.randint(1, 40)}" if rnd.random() < _YEAR_SHARE else f"_{rnd.randint(2019, 2026)}"
        if ext:
            name += "." + ext
        if name not in taken:
            taken.add(name)
            return name
    msg = "name pool exhausted"
    raise SystemExit(msg)


def cmd_tree(a: argparse.Namespace) -> int:
    rnd = random.Random(a.seed)
    root = Path(a.dir)
    if root.exists() and any(root.iterdir()):
        sys.exit(f"{root} exists and is not empty: remove it first (a tree is regenerated from scratch)")
    root.mkdir(parents=True, exist_ok=True)
    dirs: list[tuple[Path, int]] = [(root, 0)]
    names: dict[Path, set[str]] = {root: set()}
    for _ in range(a.dirs):
        parent, depth = rnd.choice([d for d in dirs if d[1] < a.depth])
        child = parent / _unique(rnd, DIR_NAMES, names[parent])
        child.mkdir()
        dirs.append((child, depth + 1))
        names[child] = set()
    lo, hi = (int(x) for x in a.lines.split("-"))
    for _ in range(a.files):
        parent, _depth = rnd.choice(dirs)
        f = parent / _unique(rnd, FILE_NAMES, names[parent], rnd.choice(EXTS))
        body = "" if rnd.random() < a.empty else "\n".join(gen_lines(a.kind, rnd.randint(lo, hi), rnd)) + "\n"
        f.write_text(body, encoding="utf-8")
    for plant in a.plant or []:
        rel, _, text = plant.partition("=")
        target = root / rel
        if rel.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
        elif target.is_dir():
            sys.exit(f"--plant {rel}: a directory with that name already exists")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text + "\n" if text else "", encoding="utf-8")
    # git cannot hold an empty directory, so every directory gets a file; a directory that must
    # stay empty in the task is made by `run mkdir -p` in the Taskfile instead.
    for d in [*sorted(p for p in root.rglob("*") if p.is_dir()), root]:
        if not any(d.iterdir()):
            body = "\n".join(gen_lines(a.kind, rnd.randint(lo, hi), rnd)) + "\n"
            (d / _unique(rnd, FILE_NAMES, set(), "txt")).write_text(body, encoding="utf-8")
    return cmd_stats(a)


def cmd_stats(a: argparse.Namespace) -> int:
    root = Path(a.dir)
    per_depth: dict[int, list[int]] = {}
    for p in root.rglob("*"):
        d = len(p.relative_to(root).parts)
        per_depth.setdefault(d, [0, 0])[0 if p.is_dir() else 1] += 1
    total_d = sum(v[0] for v in per_depth.values())
    total_f = sum(v[1] for v in per_depth.values())
    print(f"{root}: {total_d} dirs, {total_f} files; per depth (dirs/files): "
          + " ".join(f"{d}:{v[0]}/{v[1]}" for d, v in sorted(per_depth.items())), file=sys.stderr)
    return 0


def cmd_plant(a: argparse.Namespace) -> int:
    p = Path(a.file)
    lines = p.read_text(encoding="utf-8").splitlines()
    lines.insert(_position(a.at, len(lines)), a.line)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("text", help="one file of ads/notes/log/prose lines")
    t.add_argument("out")
    t.add_argument("--kind", choices=("ads", "notes", "log", "prose"), default="prose")
    t.add_argument("--lines", type=int, default=300)
    t.add_argument("--seed", type=int, default=1)
    t.add_argument("--sprinkle", help="marker of the lines the student must find (ERROR, TODO:)")
    t.add_argument("--sprinkle-count", type=int, default=20)
    t.add_argument("--plant", action="append", help="'TEXT@POS' -- insert TEXT at line POS or fraction")
    t.set_defaults(fn=cmd_text)
    ls = sub.add_parser("list", help="a list with repeats (sort/uniq/wc fodder)")
    ls.add_argument("out")
    ls.add_argument("--items", required=True, help="comma-separated distinct items")
    ls.add_argument("--lines", type=int, default=500)
    ls.add_argument("--seed", type=int, default=1)
    ls.set_defaults(fn=cmd_list)
    tr = sub.add_parser("tree", help="a directory tree with files")
    tr.add_argument("dir")
    tr.add_argument("--seed", type=int, default=1)
    tr.add_argument("--depth", type=int, default=5, help="max depth of generated dirs")
    tr.add_argument("--dirs", type=int, default=40)
    tr.add_argument("--files", type=int, default=150)
    tr.add_argument("--empty", type=float, default=0.0, help="share of empty files")
    tr.add_argument("--kind", choices=("ads", "notes", "log", "prose"), default="prose")
    tr.add_argument("--lines", default="3-30", help="lines per file, 'lo-hi'")
    tr.add_argument("--plant", action="append", help="'rel/dir/' or 'rel/file[=TEXT]' to create on top")
    tr.set_defaults(fn=cmd_tree)
    st = sub.add_parser("stats", help="per-depth counts of a tree")
    st.add_argument("dir")
    st.set_defaults(fn=cmd_stats)
    pl = sub.add_parser("plant", help="insert a line into an existing file")
    pl.add_argument("file")
    pl.add_argument("--line", required=True)
    pl.add_argument("--at", default="0.5")
    pl.set_defaults(fn=cmd_plant)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
