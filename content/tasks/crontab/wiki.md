---
tags: cron, crontab, расписание, автоматизация
---
# cron — расписание

**cron** — служба, которая раз в минуту сверяется с расписаниями и запускает то, чему пришло время:
бэкап ночью, отчёт по понедельникам, очистку каждый час. В Debian она ставится пакетом `cron`.

## Свой crontab

У каждого пользователя своё расписание:

    crontab -l      показать
    crontab -e      править в редакторе (при первом запуске Debian спросит, в каком)
    crontab -r      удалить всё — осторожно, без вопросов

    $ crontab -l
    * * * * * date >> /home/student/alive.log
    30 9 * * 1-5 /usr/local/bin/weekly-report

Хранится он в `/var/spool/cron/crontabs/<имя>`, но руками этот файл не правят: `crontab -e`
проверит синтаксис и скажет cron перечитать.

## Строка расписания

    ┌─ минута (0–59)
    │  ┌─ час (0–23)
    │  │  ┌─ день месяца (1–31)
    │  │  │  ┌─ месяц (1–12)
    │  │  │  │  ┌─ день недели (0–7, 0 и 7 — воскресенье, 1 — понедельник)
    │  │  │  │  │
    30 9  *  *  1-5   /usr/local/bin/weekly-report

| Запись | Значит |
|---|---|
| `*` | любое |
| `1,15` | 1-го и 15-го |
| `1-5` | с 1 по 5 (в днях недели — будни) |
| `*/15` | каждые 15 (в минутах — 0, 15, 30, 45) |
| `@reboot`, `@daily`, `@hourly` | сокращения: при загрузке, раз в день, раз в час |

Проверять строки удобно на [crontab.guru](https://crontab.guru/): вставляешь — он пишет словами,
когда сработает.

## Чем cron отличается от терминала

- **Нет терминала.** Вывод команды никто не увидит (или он уйдёт почтой, если она настроена) — поэтому
  `>> файл 2>&1`.
- **Короткий PATH.** У cron он почти пустой (`/usr/bin:/bin`), поэтому пути пишут полностью:
  `/usr/local/bin/weekly-report`, а не `weekly-report`.
- **Своя оболочка** — `/bin/sh`, а не bash, и без твоего `~/.bashrc`.
- **`%` — особый символ** (перевод строки): в `date +%F` его экранируют — `date +\%F`.

Что cron запускал, видно в журнале службы:

    $ sudo journalctl -u cron --no-pager | grep CMD | tail -2
    Nov 04 03:03:01 hashpass CRON[536]: (student) CMD (date >> /home/student/alive.log)
    Nov 04 03:04:01 hashpass CRON[1146]: (root) CMD (find /home/student/drafts -type f -delete)

## Системные расписания

| Где | Что |
|---|---|
| `/etc/crontab` | общее расписание системы |
| `/etc/cron.d/` | файлы с задачами пакетов и администраторов |
| `/etc/cron.hourly/`, `cron.daily/`, `cron.weekly/`, `cron.monthly/` | просто скрипты; запускаются раз в час/день/… |

В `/etc/crontab` и `/etc/cron.d/` у строки есть шестое поле — **от чьего имени** запускать:

    * * * * * root find /home/student/drafts -type f -delete

Ищешь, кто по ночам что-то делает с файлами, — смотри всё: `crontab -l` свой и root (`sudo
crontab -l`), `/etc/crontab`, `/etc/cron.d/`, а ещё таймеры systemd.

## Таймеры systemd

Современная замена cron — таймеры (`*.timer`): они пишут в журнал, умеют «догнать» пропущенный
запуск после выключения и зависят от других служб.

    systemctl list-timers

Например, `systemd-tmpfiles-clean.timer` раз в день чистит `/tmp`. Для своих простых задач cron
по-прежнему проще.

## Источники

- `man 5 crontab` — [на man7.org](https://man7.org/linux/man-pages/man5/crontab.5.html): формат строки.
- `man 1 crontab` — [на man7.org](https://man7.org/linux/man-pages/man1/crontab.1.html): `-e`, `-l`, `-r`.
- [crontab.guru](https://crontab.guru/) — проверка расписаний словами.
- [cron — Debian Wiki](https://wiki.debian.org/cron) — cron в Debian.
- [Cron — Arch Wiki](https://wiki.archlinux.org/title/Cron) — переменные, почта, таймеры как альтернатива.
