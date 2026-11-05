---
tags: журналы, var-log, journalctl, nginx, grep
---
# Журналы

Службы работают без экрана, поэтому всё важное они **записывают**. Что случилось ночью, почему
упало, кто заходил — ответ почти всегда в журнале. В Linux журналов два вида.

## Текстовые журналы в /var/log

Обычные файлы, строка на событие, новое — в конце:

| Файл | Что там |
|---|---|
| `/var/log/dpkg.log` | что ставили, обновляли, удаляли |
| `/var/log/apt/history.log` | то же, с командой apt и тем, кто её запустил |
| `/var/log/nginx/access.log` | каждый запрос к сайту |
| `/var/log/nginx/error.log` | ошибки nginx |
| `/var/log/auth.log`, `/var/log/syslog` | вход в систему, sudo, всё подряд — если стоит rsyslog |

Читают их обычными командами: `tail -n 50` — последние строки, `tail -f` — следить вживую
(выход — Ctrl+C), `grep` — нужное, `less` — листать. Старые журналы ротируются:
`access.log.1`, `access.log.2.gz` — сжатые читают `zcat` и `zgrep`.

## Кто может читать

В журналах бывают адреса, логины, куски запросов, поэтому они закрыты:

    -rw-r----- 1 www-data adm  …  /var/log/nginx/access.log

Пишет служба (www-data), читают владелец и группа **adm**. Обычному пользователю — `Permission
denied`; читать через `sudo` или попросить место в группе `adm`.

## Строка журнала доступа

    192.0.2.17 - - [12/Oct/2026:22:10:05 +0300] "GET /login HTTP/1.1" 401 512 "-" "curl/8.14.1"

Адрес клиента, время, запрос, **код ответа** (401 — нужен вход, 404 — нет такой страницы), размер
ответа, откуда пришёл, чем пришёл (User-Agent). Поля разделены пробелами, поэтому столбец
достают `awk` по номеру поля: адрес — `$1`, код ответа — `$9`. Например, все разные адреса,
которым сайт ответил 401, — в другом журнале, `shop.log`:

    $ awk '$9 == 401 {print $1}' shop.log | sort -u
    192.0.2.17
    192.0.2.40

Много 404 подряд на `/.env`, `/wp-login.php`, `/.git/config` — это сканеры: они ищут забытые
пароли и уязвимые движки и часто ходят толпой, с десятков адресов сразу. Такие приходят на любой
сайт в первые часы жизни.

## journalctl — журнал служб systemd

Службы systemd пишут в общий журнал, а не в файлы. Он двоичный — читают его `journalctl`:

    journalctl -u nginx              записи одной службы
    journalctl -u nginx -e           сразу в конец
    journalctl -u nginx -f           следить вживую
    journalctl -b                    с последней загрузки
    journalctl --since "1 hour ago"  за последний час
    journalctl -o cat                только текст сообщений, без даты и имени

Обычный пользователь видит только свои записи; всё — root и группа `systemd-journal`.

## Приоритеты

У каждой записи есть уровень важности — как у syslog:

    0 emerg   1 alert   2 crit   3 err   4 warning   5 notice   6 info   7 debug

`-p` показывает уровень и всё, что важнее:

    $ sudo journalctl -u disk-guard | tail -3
    Nov 04 02:49:56 hashpass disk-guard[48]: /dev/sdc1: заполнен на 90%, пора чистить
    Nov 04 02:49:56 hashpass disk-guard[48]: /dev/sdb1: ошибка чтения сектора 1782602
    Nov 04 02:49:56 hashpass disk-guard[48]: проверка завершена
    $ sudo journalctl -u disk-guard -p err | wc -l
    17

Утренний ритуал админа — `journalctl -p err -b`: все ошибки с последней загрузки, одним списком.
Служба сама задаёт уровень строки: в systemd достаточно начать вывод с `<3>` — это err.

## Источники

- `man 1 journalctl` — [на man7.org](https://man7.org/linux/man-pages/man1/journalctl.1.html): `-u`, `-p`, `-b`, `--since`.
- [systemd/Journal — Arch Wiki](https://wiki.archlinux.org/title/Systemd/Journal) — фильтры, размер журнала, приоритеты.
- [nginx: модуль ngx_http_log_module](https://nginx.org/ru/docs/http/ngx_http_log_module.html) — формат журнала доступа.
- [SystemGroups — Debian Wiki](https://wiki.debian.org/SystemGroups) — группа adm и другие.
