# Блок «Возможности Linux» — дизайн

Дата: 2026-11-04. Запрос пользователя (2026-11-03): «задания на разные директории и конфигурационные
linux… редактирование файлов в /etc/, чтение логов /var/log, работу с /tmp, чтобы очистилось после
reboot… понимать где что может лежать… в /opt файлы поискать… где лежит исполняемый файл и использовать
разные… службами поиграться… crontab». Свою службу пользователь хотел раньше, в другом блоке, — это уже
`my-service` (блок «Скрипты»); здесь не дублируем, службы появляются как часть конфигов и журналов.

## Место в курсе

Блок `bunnyton/linux | Возможности Linux` — после «Скрипты» и «Bash-скрипты» (последний учебный блок
курса Linux, перед Git и «Призами»). К этому месту студент знает: `ls cd cat cp mv rm`, `|`, `>`/`>>`, `grep` (вкл. `-o`, `-r`,
регулярки), `find`, `sort uniq wc`, `xargs`, `sudo`, `| sudo tee`, права, apt, процессы, `systemctl`
(start/stop/enable/status), `journalctl -u`, `/etc/hosts`, vim, скрипты, `PATH`/`which` (my-command),
`restart`-перезагрузку из my-command, свою службу (my-service).

**Решение (с codex):** см. раздел «Решения» в конце.

## Живые факты консоли (проверено 2026-11-04 в `bunnyton/pipes:1`)

- `/tmp` — **tmpfs** (`tmp.mount`, `df -h /tmp` → `tmpfs 1.6G … /tmp`); `/var/tmp` — на диске.
- `sudo reboot` в консоли **выключает машину**: консоль закрывается (nspawn выходит), сессия
  кончается. Поэтому перезагрузку изображает команда задания (как `restart` в my-command), а `reboot`,
  `poweroff`, `shutdown`, `halt` в задании про /tmp закрыты `block` с объяснением.
- `sudo systemctl restart tmp.mount` очищает `/tmp` (новый tmpfs) — это и есть честная «перезагрузка /tmp»;
  `systemd-tmpfiles --create --remove --boot` — то, что делает загрузка.
- Правила очистки: `/usr/lib/tmpfiles.d/tmp.conf`: `q /tmp 1777 root root 10d`, `q /var/tmp 1777 root root 30d`.
- `unshare -m` от root работает — проверка «что будет после перезагрузки» может идти в своём
  пространстве монтирования, не трогая `/tmp` студента.
- Журнал: `journalctl` без sudo — только свои записи («not seeing messages»); строка службы с
  префиксом `<3>` попадает в журнал с приоритетом err (`-p err`, без заголовка).
- `/var/log`: `dpkg.log`, `apt/history.log`, `journal/`; rsyslog нет (auth.log/syslog нет — и не нужно).
- `cron` в базе нет — ставим при сборке. `crontab` пишет `/var/spool/cron/crontabs/<user>` (0600,
  root:crontab) — хост его не читает, поэтому crontab проверяем `check live`.
- `useradd -m` копирует `/etc/skel` (`.bashrc .profile .bash_logout`); `timedatectl set-timezone` в
  консоли отказывает (Access denied), а nspawn переносит часовой пояс хоста — часовой пояс в задания не берём.
- Сеть консоли общая с компьютером: серверы слушают только 127.0.0.1 и на высоких портах.

## Задания (7)

Порядок в блоке: `fhs → etc-users → etc-nginx → var-log → tmp-clean → which-path → crontab`.

### 1. `fhs` — Где что лежит

Задумка: в Linux одно дерево, и у каждого каталога верхнего уровня своя работа. Ответы студент
добывает **у файлов**, а не у команд-справочников. Бриф — карта (`/etc /var /usr /home /tmp /opt
/proc /dev /boot /root`), по строчке на каталог.

| Шаг | Цель | Приёмка | Дозы |
|---|---|---|---|
| 1 | Какая версия Debian тут стоит? Узнай у файла в /etc | `accept output` «13.x» (`/etc/debian_version`) или `VERSION_ID="13"` (`os-release`) | tries: «что лежит в /etc — какие имена про версию?» |
| 2 | Какая оболочка у student и где это записано | `accept output "student:x:1000:1000:[^\n]*:/bin/bash"` (`/etc/passwd`, `getent passwd`) | доза на `Is a directory`; tries → «файл со списком пользователей» |
| 3 | Какой процессор у машины | `accept output "model name\s*:"` (`/proc/cpuinfo`) | on enter не нужен; on pass: размер 0 у `ls -l` — файл пишет ядро при чтении |
| 4 | Где на самом деле лежит /bin | `accept output "bin -> usr/bin"` (`ls -l /`) | on pass: usrmerge |

Финал — мем про карту.

### 2. `etc-users` — Учётки — это файлы в /etc

Задумка: пользователи и группы — строки в `/etc/passwd`, `/etc/group`; домашний каталог новичку
собирается из `/etc/skel`. Бриф — база `useradd` (`sudo useradd имя`, `-m` — с домашним каталогом).

| Шаг | Цель | Приёмка | Дозы |
|---|---|---|---|
| 1 | Заведи учётку стажёра intern — с домашним каталогом | `observe bool /home/intern/.profile` (эталон `sudo useradd -m intern`) | `hint output "already exists"` → userdel; tries: «есть ли у intern дом? ls /home» |
| 2 | Каждому новому сотруднику — ПАМЯТКА.txt из твоего каталога; проверь на intern2 | `observe /etc/skel/ПАМЯТКА.txt` + `observe bool /home/intern2/ПАМЯТКА.txt` | доза `skel.md` после первой неудачи (tries 3 нельзя — линт ≥5: доза `hint tries 5 read skel.md`? нет — **вопрос** «откуда у intern взялись .bashrc и .profile?», `man useradd` → SKEL) |
| 3 | Дай intern право на sudo и покажи, что оно есть | `accept output` (`groups=…(sudo)` / `intern : … sudo` / `sudo:x:27:…intern`) | on pass: членство в группе — строка в /etc/group, её можно было поправить и в vim |

Ловушка шага 2: скопировать прямо в /home/intern2 — проверка не примет, нет в шаблоне.

### 3. `etc-nginx` — Конфиг и служба

Задумка: программа читает конфиг **при запуске** — поправил файл, а ничего не поменялось, пока служба
его не перечитала. Плюс: проверка конфига перед перезапуском. В образе nginx; сайт отдела — 127.0.0.1:8472.

| Шаг | Цель | Приёмка | Дозы |
|---|---|---|---|
| 1 | Сайт переезжает на порт 8473: http://localhost:8473/ | `check live` curl 8473 отдаёт страницу | `hint output "Connection refused"` (после правки) → доза `reload.md`: «конфиг читается при старте»; `Permission denied` → sudo; tries: «где nginx хранит настройки? grep -r 8472 /etc/nginx» |
| 2 | Коллега «добавил страницу» и перезапустил — сайт лежит. Подними | `on enter apply break`: в конфиг добавляется блок с ошибкой (нет `;`), nginx перезапущен и упал. Приёмка `check live`: nginx active и curl 8473 | `hint output "failed"` → «почему — журнал службы»; доза `test.md` на `emerg`: `nginx -t` |

### 4. `var-log` — Журналы

Задумка: что случилось — спроси у журналов. Текстовые журналы в `/var/log`, журнал systemd — `journalctl`.
Образ: nginx (сам ставится при сборке → настоящая строка в dpkg.log), `access.log` (data, ~600 строк,
сканер 404 с одного IP), служба `disk-guard`, которая при загрузке пишет 200 строк, из них 17 ошибок `<3>`.

| Шаг | Цель | Приёмка | Дозы |
|---|---|---|---|
| 1 | Когда на сервер поставили nginx? | `accept output` строки установки nginx (`dpkg.log` `install nginx` / `history.log`) | tries: «журналы — в /var/log; какой из них про пакеты?» |
| 2 | С какого адреса сыпятся 404 на сайт? Покажи только адрес | `observe output` (эталон `sudo grep ' 404 ' … \| grep -oE '^[0-9.]+' \| sort -u`) | `Permission denied` → доза `adm.md` (журналы читает root/adm); `hint output " 404 "` (строки целиком) → «только адрес — помнишь grep -o?» |
| 3 | Сколько ошибок записала служба disk-guard с загрузки? Покажи число | `accept output "(?m)^\s*17\s*$"` | `not seeing messages` → sudo; tries → `man journalctl` «priority»; доза `prio.md` на вывод без фильтра |

### 5. `tmp-clean` — /tmp и перезагрузка

Задумка: `/tmp` живёт в памяти и пустеет при перезагрузке, `/var/tmp` переживает её, но тоже
чистится по возрасту; правила — `tmpfiles.d`. «Перезагрузку» изображает команда `restart`
(`systemctl restart tmp.mount` + `systemd-tmpfiles --create --remove --boot`).

| Шаг | Цель | Приёмка | Дозы |
|---|---|---|---|
| 1 | /tmp — на диске или в памяти? | `accept output` строка `tmpfs … /tmp` (`df`, `findmnt`, `mount`) | бриф: `df -h /home` как пример |
| 2 | Через сколько дней система чистит /var/tmp? | `accept output "/var/tmp\s+1777\s+root\s+root\s+30d"` | доза `tmpfiles.md` на tries 5: «правила очистки — tmpfiles.d, `man tmpfiles.d`» |
| 3 | builder после каждой перезагрузки нужен /tmp/builder (владелец student). Сделай, чтобы появлялся сам, и проверь restart | `check live`: правило `d /tmp/builder` в `/etc/tmpfiles.d/*.conf` и после `restart` каталог есть, владелец student | `hint cmd mkdir` → «а после restart он на месте?» |

`block reboot|poweroff|shutdown|halt` — «настоящая перезагрузка закроет консоль; её изображает restart».

### 6. `which-path` — Где лежит программа

Задумка: команда — это файл, найденный по `PATH`; версий одной программы может быть несколько, и
запускается первая по `PATH`. /opt — место для сторонних программ. Среда: старый
`/usr/local/bin/report` (1.0), в `/opt/acme/` (сотни файлов вендора) — `report-2.0/bin/report`,
`report-2.1/bin/report`, а также каталоги `share/doc/report` (ловушка для `find -name` без `-type f`).

| Шаг | Цель | Приёмка | Дозы |
|---|---|---|---|
| 1 | Где лежит report, который запускается по имени? | `accept output "/usr/local/bin/report"` | — (which/type известны из my-command) |
| 2 | В /opt поставили новые версии. Найди все файлы report в /opt | `observe output` + `similarity 100` (эталон `find /opt -name report -type f`) | лишние каталоги → «в списке есть каталоги?» |
| 3 | Запусти 2.1, не трогая старую | `accept cmd "report" ok` + `accept output "report 2\.1"` | — |
| 4 | Пусть просто report запускает 2.1 | `accept cmd "report" ok` + `accept output "^report 2\.1"` + `block report match "^[^ ]*/"` (только по имени) | доза `hash.md` на `No such file or directory` (bash помнит старый путь: `hash -r`); tries: «PATH читается слева направо» |

on pass шага 4: export живёт до выхода, навсегда — строка в `~/.bashrc` (или ссылка в /usr/local/bin).

### 7. `crontab` — Расписание

Задумка: cron запускает команды по расписанию; свои задачи — `crontab -e`, системные — `/etc/crontab`,
`/etc/cron.d/`. В образе cron + `/usr/local/bin/weekly-report` + `/etc/cron.d/tidy-drafts`
(каждую минуту удаляет файлы из `~/drafts`; до шага 3 там пусто — безвредно).

| Шаг | Цель | Приёмка | Дозы |
|---|---|---|---|
| 1 | Пусть каждую минуту в ~/alive.log дописывается текущее время | `check live`: в crontab student строка `* * * * *`, в alive.log ≥ 2 строк | tries: «прошла ли минута? cat alive.log» ; `man 5 crontab` |
| 2 | weekly-report — по будням в 9:30 | `check live` `crontab -l -u student` ~ `30 0?9 * * (1-5\|mon-fri\|1,2,3,4,5) …weekly-report` | доза: crontab.guru, порядок полей |
| 3 | Кто-то каждую минуту стирает ~/drafts. Найди и останови | `on enter apply drafts` (кладёт черновики); `check live`: ни в /etc/cron.d, ни в /etc/crontab, ни в crontab root нет действующей строки про drafts, черновик есть | tries: «в твоём crontab пусто — а у системы?» |

## Общее

- Все задания от `student` + sudo; данные — `data/` (+ команда генерации комментарием); финалы — `meme.py`.
- `wiki.md` каждому (теги, настоящий вывод команд из консоли, `## Источники` — проверены curl).
- Проверка: сборка в изолированном доме под `flock`, живой прогон pexpect: предпосылка, ошибки → дозы,
  решение → зачёт → финал. Линты `tests/content`.
- На prod не пушим; в `deploy.sh` блок добавляется (новое — скрытым при будущем деплое).

## Решения

Вычитка codex (2026-11-04) и что из неё принято:

1. **fhs оставлен** (codex предлагал убрать и перенести карту в брифы). Пользователь прямо просил
   «понимать, где что может лежать» — короткое задание-карта, четыре шага, ответ добывается
   поиском нужного файла. Вывод целого файла (`cat /etc/passwd`) принимается намеренно: найти файл и
   есть урок.
2. **var-log: шаг «когда поставили nginx» убран** (busywork). Остались 404-сканер (`observe output`,
   строго) и счёт ошибок `journalctl -p err`; регулярка числа — `\A[ \t]*17[ \t]*\n?\Z` (весь вывод —
   одно число), `echo`/`printf` закрыты.
3. **which-path: шаг «запусти 2.1 полным путём» убран** — стал добавкой `on pass` шага 2. Шаг 3
   требует постоянства: `check live` запускает новую оболочку студента (`runuser … bash -lic`) —
   `export` в одной оболочке не принимается, `~/.bashrc`, ссылка в `/usr/local/bin` или `~/bin` —
   принимаются. Шаг 1 — ровно одна строка вывода с путём (не дамп `find`). `block` по полному пути не
   работает (база команды — слово как набрано), поэтому его нет.
4. **crontab**: синтаксис строки — в брифе (до первой попытки); alive.log до шага не существует;
   ждать ≥ 1 строки (минута), а не две. Доза про системные расписания — `hint cmd crontab` (после
   первого `crontab -l`), а не при входе.
5. **tmp-clean**: `block` — отдельное правило на каждую команду (`reboot`, `poweroff`, `shutdown`,
   `halt`, `systemctl reboot|poweroff|halt|kexec`). Шаги 1–2 принимают любой вывод, где видна
   нужная строка (`df`, `findmnt`, `mount`; `grep -r` или `cat` нужного файла).
6. **useradd, df, nginx -t, journalctl -p, hash -r** — в брифах и дозах (`groups.md`, `reload.md`,
   `test.md`, `prio.md`, `journal.md`, `tmpfiles.md`, `path.md`, `hash.md`, `system.md`); cut/awk
   не нужны нигде.
7. **Место блока — после «Bash-скрипты»** (вторая вычитка codex): bash-path учит менять PATH навсегда
   (`~/.bashrc`, `source`, ссылка в /usr/local/bin), which-path применяет это к выбору версии; из
   дозы `path.md` объяснение механизма убрано — осталось про порядок и `type -a`. cron тоже
   выигрывает: задачи cron — команды и скрипты в своём окружении.
8. **etc-users и etc-nginx не склеиваются** (codex согласен): разные модели — данные учёток и
   жизненный цикл конфига службы.

Найдено по ходу:

- В консоли корень `/` принадлежит uid 1000 (student): так выходит у overlay, собранного
  пользователем-автором. `systemd-tmpfiles` из-за этого отказывается работать вовсе («unsafe path
  transition»), и правила `tmpfiles.d` не применяются ни при загрузке, ни вручную. В tmp-clean это
  обходит `on enter apply rootfix` (`chown root:root /`). Движок не правился: на владельца корня
  опирается хост (метка готовности в `/`). Это стоит чинить в движке отдельно — заодно это дыра: владелец `/`
  может переименовать `/etc`.
- Новый curl пишет «Could not connect to server», а не «Connection refused»: подсказки на
  `Connection refused` (в т.ч. в `services`) больше не срабатывают; в etc-nginx — `Failed to connect`.
- `observe` в шаге с `check live` не применяется (шаг становится «live») — всё, что нужно проверить,
  пишется в саму команду `check live`.
