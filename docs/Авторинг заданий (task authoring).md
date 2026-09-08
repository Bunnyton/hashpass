# Авторинг заданий — гайд и справочник

Как написать своё задание в DSL, собрать его и прогнать. Всё библиотечное (Python API) —
CLI пока нет, поэтому «команды» = короткие Python-скрипты + `pytest` для tier3-прогона.

Оглавление: [Обзор](#обзор) · [Быстрый старт](#быстрый-старт) · [Плейграунд](#плейграунд-одной-командой) ·
[DSL](#dsl--полный-справочник) · [Контракт HP_*](#контракт-hp_--exec-обработчики) ·
[Как работает приём](#как-работает-приём) · [API](#api--команды) · [Реестр](#реестр-локальный--глобальный) ·
[Полный пример](#полный-пример-proc-audit) · [Подводные камни](#подводные-камни)

---

## Обзор

Две операции, никаких «режимов»:

- **`build`** — собрать образ (или задание = образ + логика) из рецепта в слой.
- **`run`** — запустить контейнер. Есть блок `stage` → это **задание** (полный цикл приёма). Нет `stage` → **чистый образ** (просто среда).

Один формат файла: **`Imagefile` = `Taskfile`**, один язык. Есть `stage` → задание, нет → образ.

Задание строится **на образе** (Docker-подобное наследование `from`), приём **деривируется**
из эталонного решения (`solve`) и наблюдаемых путей (`observe`) — сравнение толерантное
(size-adaptive Jaccard/MinHash), а не «команда в команду».

---

## Быстрый старт

**1. Напиши `Taskfile`** (обычный текстовый файл, имя любое):

```
image hello-grep:1
run  printf 'alpha\nTODO fix\nbeta\n' > /notes.txt

stage "Вытащи строку с TODO из /notes.txt в /found.txt"
  solve   grep TODO /notes.txt > /found.txt
  observe /found.txt
```

**2. Собери и запусти** — авторская команда `hashengine` (нужен `systemd-nspawn` + scoped sudo; базовый
rootfs `<home>/base/rootfs.tar` — готовится один раз вручную, docker в рантайме не нужен):

```bash
hashengine build Taskfile        # собрать; base-rootfs Debian создастся сам при первом build
hashpass run <логин>/hello-grep:1  # запустить локально: интерактивная сессия задания
```

Внутри `run` — промпт: вводишь Linux-команды, они выполняются в контейнере, система грейдит
после каждой команды и молча продвигает стадии (появляется следующая цель) — обязательных фраз
вроде «принято»/«завершено» НЕТ, это на усмотрение автора (`on pass` / `voice bye` / финал);
подсказки даются по условиям; `exit` — выйти. Неправильное решение просто не проходит стадию.

> `hashengine` появляется и активируется после `make install` (в корне репо); без установки —
> `python3 -m hashengine build …`. Хранилище автора — `~/.hashengine/` (base-rootfs кэшируется там же).

---

## Плейграунд одной командой

Интерактивно решать задание — `hashpass run` (выше). А для **CI / быстрой само-проверки** есть
скрипт `docs/examples/author_playground.py`: собирает твой `Taskfile` и **автоматически прогоняет
эталонное решение по всем стадиям**, печатая приём/ключ по каждой — проверить, что задание решается:

```bash
# нужен готовый <home>/base/rootfs.tar + scoped sudo для nspawn (docker не требуется)
TMPDIR=/var/tmp/hp-pytest python3 docs/examples/author_playground.py content/tasks/proc-audit/Taskfile
```

Выведет по каждой стадии: `stage 0: ADVANCED key{...}` — если эталон принялся. Правь `Taskfile`,
перезапускай. (Скрипт короткий — можно скопировать и кормить свои команды вместо эталона.)

---

## DSL — полный справочник

Строчный, **блоки — отступами** (как в Python/YAML). Ключевые слова английские, содержимое реплик — любое.
Пустые строки и строки, начинающиеся с `#`, игнорируются; инлайновый `#` внутри `run`/`solve` сохраняется.

### Директивы образа (верхний уровень, колонка 0)

| Директива | Синтаксис | Что делает |
|---|---|---|
| `image` | `image <name>:<ver>` | Самоимя. **Необязательно** — иначе имя даётся при сборке (`-t name:ver`, иначе по каталогу). Если есть — один раз. Без `:ver` → `latest`. |
| `from` | `from <ref>[, <ref> …]` | Наследование, **транзитивно**: тянет и всё, из чего собран родитель. Мульти-`from`: порядок = приоритет (правее побеждает при конфликте путей). |
| `copy` | `copy <src> <dst>` | Скопировать хостовый `<src>` в образ по `<dst>` (запекается в слой). |
| `run` | `run <команда>` | Выполнить команду на сборке (запекается — среда всегда у студента). |
| `readme` | `readme <файл>` | Файл теории (относительный путь). |
| `hidden` | `hidden <src>` | Каталог `<src>` → скрытый слой `/hp/work` (грейдеры/seed/verify/арт), студенту не виден. |

```
image log-lab:1
from  base, coreutils-lab           # транзитивное + композиция
readme theory.txt
copy   assets/  /home/student/       # запекается
run    apt-get install -y procps     # запекается (среда)
hidden grade/                        # → /hp/work, невидим студенту
```

### Блок `stage` (задание)

`stage "<сообщение>"` открывает стадию; её тело — с отступом. Стадий может быть несколько
(проходятся по порядку; стадия N видит эффекты стадий 0..N-1).

| Под-директива | Синтаксис | Что делает |
|---|---|---|
| `solve` (инлайн) | `solve <одна команда>` | Эталонная команда. Для деривации + как «prep» для следующих стадий. |
| `solve:` (блок) | `solve:` + строки глубже | Многокомандный эталон (в одном шелле, cwd/env живут внутри стадии). `<output>` = stdout **последней** команды. |
| `variant` / `variant:` | `variant <команда>` или блок | Ещё одно решение той же задачи. Эталон = наблюдаемое, ОБЩЕЕ для `solve` и всех `variant` (какой командой — не важно; расходятся — сборка падает). Требует `observe`. |
| `observe` | `observe <путь> [путь…]` | Что сравнивать: файл, каталог (рекурсивно), или несколько путей. |
| `observe bool` | `observe bool <путь…>` | Проверять только СУЩЕСТВОВАНИЕ/тип (файл/каталог/нет), без содержимого. Эталон = что оставил `solve` (есть/нет). |
| `observe output` | `observe output` | Приём по **stdout** команды (чистый, по OSC-133), а не по ФС. Порог — `settings similarity` (100 = строго). |
| `accept cmd` | `accept cmd "<подстрока>"` | Стадию проходит команда, содержащая подстроку (без ФС-грейда). Можно несколько. |
| `exclude` | `exclude <шаблон…>` | Выкинуть шум (fnmatch-глоб по ключу/сегменту: `*.log`, `.cache`). |
| `neutral` | `neutral <база…>` | «Осмотр» — команды, НЕ считающиеся попыткой (для `tries`/hint): `ls cd cat pwd`. |
| `deny` | `deny <база…>` | Политика: эти команды **не выполняются** в консоли (шелл шэдоуит их и отказывает) и не засчитывают стадию. Взаимоисключимо с `allow`. |
| `allow` | `allow <база…>` | Политика: выполняются и засчитывают **только** эти команды (плюс `neutral`-навигация и `cd`/`exit`); остальное шелл блокирует до запуска. Напр. `echo 3`-подстава просто не выполнится. |
| `check` | `check exec <файл-или-команда>` | Кастомный приём кодом (`exit 0` = принято). Escape для недетерминированного. |
| `on enter` | `on enter <действие>` | Действие при входе в стадию. |
| `on pass` | `on pass <действие>` | Действие при прохождении стадии. |

```
stage "Собери строки ERROR из /var/log/app в /errors.txt"
  solve    grep -rh ERROR /var/log/app > /errors.txt
  observe  /errors.txt
  exclude  .cache *.log
  neutral  ls cd cat pwd less head tail
  on enter exec seed.sh
  on pass  exec cheer.sh
  # check exec verify.sh          # если нужен кастомный приём вместо derived
```

Многокомандный `solve:` (важно — `solve:` без инлайна, команды на следующих строках глубже):

```
stage "Отсортируй и посчитай уникальные"
  solve:
    sort /fruits.txt > /sorted.txt
    uniq /sorted.txt > /unique.txt
  observe /unique.txt
```

### Действия

Действие всегда явное: `<verb> <value>`.

| Действие | Пример | Смысл |
|---|---|---|
| `say "..."` | `say "Собираем логи."` | Показать текст (печатающий вывод). |
| `say dramatic "..."` | `say dramatic "Финал…"` | То же, но медленно, с паузами. |
| `show file <путь>` | `show file art/ok.txt` | Показать файл из `/hp/work/<путь>` (большой → пейджер). |
| `exec <файл-или-команда>` | `exec verify.sh` / `exec grep -q ERROR /errors.txt` | Делегировать: если первый токен — файл в `/hp/work` → выполнить **файл** (по shebang), иначе → shell-команда. Контракт — [`HP_*`](#контракт-hp_--exec-обработчики). |

`exec` авто-детектит файл-vs-команду сам, без явного `file`/`cmd`. Именованные аргументы
`key=value` после файла → в env как `HP_ARG_key` (первый аргумент скрипта — всегда команда студента).

### Интерактив (по спеке §7)

**Условные подсказки** — голого `stuck` нет, условие всегда явное. `hint <условие> <действие>`,
первое сработавшее (в порядке) выигрывает:

| Условие | Пример | Срабатывает |
|---|---|---|
| `tries N` | `hint tries 5 say "Загляни в /var/log"` | После N реальных попыток (без `neutral`-команд). |
| `idle N` | `hint idle 90 exec idle.sh` | После N секунд без прогресса. |
| `cmd <база> [has <флаги>] [missing <флаги>]` | `hint cmd grep missing -i say "Добавь -i"` | Студент запустил `<база>` с/без флагов. |
| `output "<подстрока>"` | `hint output "Permission denied" say "Нужен sudo?"` | Вывод содержал подстроку. |

**`voice`** — приветствие/прощание (событийно), **`settings`** — рендер, **`react`** — обработчик на каждую команду:

```
settings
  type-mode  normal          # instant | normal | dramatic (по умолчанию normal)
  type-speed 55              # символов/сек (умолчание; печать всегда посимвольная, ровно)
  pager on                   # большие show file → пейджер
  workdir /home/student      # база для read/show file, если файла нет в скрытом /hp (умолчание — дом студента)

voice
  hello  say "Сегодня приручаем логи."          # при входе (первая стадия)
  bye    say "Готово."                          # когда все стадии пройдены

react on command exec watch.sh   # (перехватчик на каждую команду — полный HP_* контекст)
```

> Порядок расширения: новый verb/условие/событие — **аддитивная** правка парсера, синтаксис остального не меняется.

---

## Контракт `HP_*` (exec-обработчики)

`exec <файл>` запускает **любой исполняемый файл** (shebang выбирает интерпретатор) из `/hp/work`,
внутри контейнера, с примонтированным скрытым слоем `/hp` — **только на этом запуске** (команды
студента `/hp` не видят: §4.2 невидимость через mount-namespace).

**Вход:**

| Канал | Что |
|---|---|
| `argv[1]` | текущая команда студента (сырая строка) |
| `HP_TRIES` | реальные попытки на стадии (без `neutral`) |
| `HP_LAST_OUT` | вывод последней команды (NUL-очищен, ограничен) |
| `HP_STAGE` | номер текущей стадии |
| `HP_STATE` | путь к `/hp/state.json` (rw → память между вызовами) |
| `HP_HISTORY` | путь к файлу истории |
| `HP_ROOTFS` | `/` (ФС студента внутри контейнера) |
| `HP_ARG_*` | именованные аргументы из DSL (`exec f.sh expected="a b"` → `HP_ARG_expected`) |

**Выход** (смысл — по директиве):

| Директива | Ответ |
|---|---|
| `hint` / `say` / `voice` | **stdout** = текст показать |
| `check` / условие | **exit**: `0` = принято/разрешено |
| `solve` | **stdout** = команды эталона (или сам файл — скрипт-решение) |
| `on enter/pass` / `react` | сайд-эффекты; `stdout` (если есть) — показать |

Пример грейдера (`/hp/work/verify.sh`, положи через `hidden grade/`):

```sh
#!/bin/sh
# принять, если студент реально нашёл строки ERROR
[ -s /errors.txt ] && grep -q ERROR /errors.txt
# exit-код команды = вердикт (0 = принято)
```

---

## Как работает приём

Две модели, выбираются по стадии:

1. **Derived (по умолчанию)** — `solve` + `observe` → задание строится, эталон гоняется несколько
   раз на **смонтированной цепочке образа**, наблюдаемые пути канонизируются в толерантный
   инвариант. Приём студента = сравнение его наблюдаемого состояния с этим инвариантом.
   **Требование: наблюдаемое детерминировано** (вывод в файл, без времени/PID/случайности) —
   иначе деривация бросит `vacuous canonical`.

2. **`check exec`** — escape для невыразимого/недетерминированного (напр. процессы, `.tar.gz`).
   Твой скрипт решает всё: `exit 0` = принято. Приоритет: если у стадии есть `check` — он побеждает.

> Приём — **по результату**, не по совпадению команд. Студент может решить иначе, чем эталон.

---

## CLI — команды

```bash
# автор (hashengine):
hashengine build <Taskfile> [-t name:ver]        # собрать; имя: -t > image-строка > каталог
hashengine images                                # список собранного (name:ver + kind: task|image)
hashengine login <registry-url>                  # логин/пароль → токен (кэш 7 дней)
hashengine push <name:ver> --task <N> --title "…"  # опубликовать задание в пул под номером N
hashengine serve                                 # поднять пул (реестр + веб-панель)
# студент (hashpass):
hashpass                        # без аргументов → подтянуть каталог и показать задания по номерам
hashpass register / login       # регистрация (ФИО+группа) / вход на пул
hashpass run <номер|name:ver>   # запустить задание; по прохождению результат уходит на пул
```

`hashengine` доступна после `make install`; иначе — `python3 -m hashengine …`. Ошибки пользователя
(кривой Taskfile, нет базового rootfs, `push` без `login`, неизвестный ref) → чистое `<cmd>: <причина>` в
stderr, без трейсбека. `rmi` пока нет (удаление root-owned слоёв требует `sudo rm`, не выдан).

---

## Библиотечный API

CLI — тонкая обёртка над этими вызовами; для программного использования / CI:

```python
# Парсинг
from hashpass.recipe.parse import parse_recipe, load_recipe
recipe = load_recipe("Taskfile")           # или parse_recipe(text)

# Собрать ЗАДАНИЕ (образ + деривация приёма + скрытый /hp + метаданные)
from hashpass.taskbuild import build_task
from hashpass.imagestore.store import ImageStore
store = ImageStore(work / "images")
stored = build_task(recipe, store, *, base_tar, workdir, passes=3, sudo=True)
#   passes >= 2 (проходы деривации). Артефакты кладутся рядом с образом: images/<name>/<ver>/task/

# Запустить ЗАДАНИЕ (сессия студента)
from hashpass.taskrun import run_task
sess = run_task(ref, store, workdir, *, base_tar, student_id, nonce,
                sink=<stdout write>, sleep=<time.sleep>)   # sink/sleep инъектируемы (для тестов)
sess.enter()                     # -> list[str]: on_enter/voice.hello (отрендеренные)
res = sess.feed(command, *, ts)  # -> FeedResult(advanced, stage, local_key, hint)
sess.teardown()

# Чистый ОБРАЗ (без stage)
from hashpass.build import build, run_image
img = build(recipe, store, *, base_tar, workdir, sudo=True)      # -> StoredImage
runner = run_image(ref, store, workdir, *, base_tar)             # -> NspawnRunner (среда)
runner.run(["sh","-c","echo hi"]); runner.teardown()
```

**Прогнать как tier3-тест** (рекомендуемый способ проверки — как `tests/content/test_proc_audit.py`):

```bash
TMPDIR=/var/tmp/hp-pytest python3 -m pytest tests/content/test_моё.py -m tier3 -v
```

Тиры: `tier1` — чистая логика; `tier2` — loopback/rootless; `tier3` — реальный `systemd-nspawn` +
scoped sudo. Обычный прогон исключает tier3 (`pytest -m "not tier3"`). Для tier3 — `TMPDIR=/var/tmp/hp-pytest`
(в `/tmp` тесно + копится root-owned мусор).

---

## Реестр (локальный + глобальный)

Как в Docker: локальный кэш (`ImageStore`) + реестр по имени. **Push** — под токеном, **pull** — аноним,
**локальный реестр** — без auth. Сервер запускается **только локально** (тесты), деплоя нет.

```python
from hashpass.registry.local import LocalRegistry
reg = LocalRegistry(root=work / "registry")     # ФС-реестр, без auth
reg.push(store, "log-lab:1")                     # копирует образ + его from-замыкание
reg.pull("log-lab:1", other_store)               # тянет замыкание обратно

# Глобальный (HTTP): логин/пароль → токен (TTL 7 дней), кэшируется
from hashpass.registry.remote import RemoteRegistry
from hashpass.registry.creds import CredentialCache
cache = CredentialCache(Path.home() / ".hp-creds.json")
remote = RemoteRegistry(base_url="http://127.0.0.1:8080", cache=cache)
remote.login("alice", "s3cret")                  # кэширует токен, дальше не спрашивает 7 дней
remote.push(store, "log-lab:1")                  # использует кэшированный токен
remote.pull("log-lab:1", store)                  # аноним

# Локальный тест-сервер (реестр-сервер)
from hashpass.registry.server import make_server
from hashpass.registry.passwords import UserStore
import secrets
users = UserStore(work / "users.json"); users.add("alice", "s3cret")
srv = make_server(store, users, secrets.token_bytes(32))   # binds 127.0.0.1:0 — ТОЛЬКО тесты
```

---

## Полный пример: `proc-audit`

Реальное двухэтапное задание (`content/tasks/proc-audit/Taskfile`): установка пакета + аудит процессов.

```
image proc-audit:1

stage "Установи procps (apt) и запиши dpkg-статус в /install-status.txt"
  solve:
    apt-get update >/dev/null 2>&1
    apt-get install -y procps >/dev/null 2>&1
    dpkg -s procps | grep '^Status:' > /install-status.txt
  observe /install-status.txt

stage "Запусти фоновый sleep 600 и посчитай sleep-процессы через pgrep в /proc-count.txt"
  solve:
    sleep 600 &
    sleep 0.3
    pgrep -x sleep | wc -l > /proc-count.txt
  observe /proc-count.txt
```

Почему так: в базе `debian:trixie-slim` **нет `ps`/`pgrep`**, поэтому установка `procps` — реально
нужный шаг (и большое изменение ФС), а стадия 2 использует установленный `pgrep`. Приём деривируется
из **детерминированных** артефактов (dpkg-статус; счётчик = 1), а не из волатильной таблицы процессов.
Проверка: `tests/content/test_proc_audit.py` (tier3, ~80с — реальные apt-установки).

---

## Подводные камни

- **Детерминизм наблюдаемого.** derived-приём требует, чтобы `observe`-пути были одинаковы между
  прогонами. Пишите результат в файл; избегайте времени/PID/случайности в наблюдаемом. Иначе — `check exec`.
- **nspawn выполняет каждую команду отдельно.** Фоновый процесс из одной команды НЕ доживает до
  следующей. Хочешь искать процессы — запусти И найди в **одной** команде (`sleep 600 & …; pgrep …`).
- **Сеть/apt.** В контейнере есть сеть — `apt-get update && apt-get install` работают (но каждый
  прогон деривации переустанавливает → медленно; держи `passes=2` для тяжёлых заданий).
- **Базовый образ тонкий.** `debian:trixie-slim` — есть `sh`/`apt`/`dpkg`/`grep`/`sleep`/`awk`, **нет
  `ps`/`pgrep`/`python3`**. Нужен инструмент — `run`-установи его в образ или `apt` в стадии.
- **`hidden`-скрипты — `#!/bin/sh`** (в базе нет `python3`), и `chmod +x`.
- **`exclude` — глоб**, не префикс (fnmatch по ключу/сегменту).
- **Абсолютные `observe`-пути** (`/errors.txt`) корректны — ведущий `/` срезается, путь ложится под rootfs.
- **`build_task(passes=1)` запрещён** — деривации нужно ≥2 проходов, чтобы отсечь шум.
- **`/hp` невидим студенту by construction** — не пытайся класть туда то, что студент должен видеть;
  видимое кладётся через `copy`/`run` в образ.
