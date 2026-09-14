# Указания для Claude Code

## Язык общения
Отвечай пользователю **по-русски** — весь UI-текст, объяснения, статусы.
Идентификаторы кода, commit-subjects и shell-вывод оставляй как принято
(обычно на английском).

## Как работать (в этом порядке)

### 1. Skills перед ответом
Перед любым действием — проверяй, есть ли подходящий `superpowers:*` skill,
и если да — вызывай его. Особенно:
- **`superpowers:brainstorming`** — новая фича / крупный дизайн, до кода.
- **`superpowers:systematic-debugging`** — баг / неожиданный вывод.
- **`superpowers:verification-before-completion`** — перед словами «готово»,
  «зелёное», «работает», перед `git commit` / `git push`.
- **`superpowers:test-driven-development`** — новая логика / фикс, тест до кода.

### 2. Evidence перед словами
Никаких «готово / должно работать / зелёное» без свежего вывода прогона:
`pytest ...`, `ruff ...`, `expect ...`, `curl ...` — с exit-кодом и результатом
в этом же ответе. «Кажется» и «наверное» — не evidence.

### 3. Читай полный вывод
Полный traceback, полный stderr. Не гадай по одной строке. Ошибка `TypeError`
без стека — тянет за собой другую ошибку через 20 минут.

### 4. Батч, а не пинг-понг
Одну задачу — один коммит с осмысленным сообщением. Не бампать версию за
каждую строку CSS. Версию поднимай, когда это реально релиз для клиентов,
и `install.sh` уже переставляет с `--force-reinstall` (см. `web.py`).

### 5. Быстрый цикл — реальный терминал
Веб — проверяй curl-ом к живому серверу, TUI — через `expect`/`pexpect` в
реальном pty. `feed()`-тесты и tier1 ловят не всё. См. memory
[`verify-with-expect-before-delivery`](/home/debi/.claude/projects/-home-debi-LinuxWork-hashpass/memory/verify-with-expect-before-delivery.md).

## Границы

- Пул на 135.106.177.228 — **prod**. Не выкатывать туда через `pip install`
  или `hashengine push` из этой сессии, если пользователь не попросил явно.
  Полная политика — memory [`rebuild-safety-boundaries`](/home/debi/.claude/projects/-home-debi-LinuxWork-hashpass/memory/rebuild-safety-boundaries.md).
- Пуш в `origin/main` разрешён (снял пользователь 2026-09-08).
- `sudo` — только через NOPASSWD-белый список: `systemd-nspawn`, `machinectl`,
  `mount`, `umount`, `chroot`, `tar`, `rsync`, `systemctl`. Всё остальное
  требует пароль → останови и попроси.

## Что не делать
- Не создавать worktree в `.claude/worktrees/` за пределами `chown debi:debi`
  (владелец файлов зависит от того, кто исполнил `git worktree add` — если
  root, чистить только через `sudo rsync --delete`).
- Не плодить мелкие фиксы с бампом версии.
- Не отвечать «работает» без прогонки.
