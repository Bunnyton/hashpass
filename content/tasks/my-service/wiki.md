---
tags: процессы, службы, systemd, юнит
---
# Своя служба: скрипт и юнит systemd

Чужими службами командовать — `systemctl start/stop/enable` ([wiki про службы](/web/wiki/bunnyton/services)).
Своя служба — это всего два файла: **программа**, которая работает долго, и **юнит**, который
объясняет systemd, как её запускать. Дальше systemd сам: запустит при загрузке, соберёт вывод в
журнал, поднимет после падения.

## Программа: бесконечный цикл

Служба не должна заканчиваться сама. Простейшая — bash-скрипт с циклом:

    #!/bin/bash
    while true; do
        echo "тик"
        sleep 5
    done

`while true` повторяет тело без конца, `sleep` даёт процессору отдохнуть между кругами — без него
цикл съест целое ядро. Останавливают такой скрипт сигналом; `systemctl stop` так и делает.

Две обязательные мелочи: первая строка `#!/bin/bash` (чем исполнять) и право на исполнение —
`chmod +x`. Писать в файлы журнала не нужно: всё, что программа печатает, systemd сам
складывает в журнал.

## Юнит-файл

Юниты администратора лежат в `/etc/systemd/system/`, имя файла — имя службы:
`/etc/systemd/system/mailcheck.service`. Разделы:

    [Unit]
    Description=проверка почты            что это — видно в systemctl status

    [Service]
    ExecStart=/usr/local/bin/mailcheck    что запускать — ПОЛНЫЙ путь
    User=nobody                           от чьего имени (по умолчанию root)
    Restart=on-failure                    поднимать ли после падения
    RestartSec=2                          через сколько секунд

    [Install]
    WantedBy=multi-user.target            куда «подвесить» при enable

Минимум — `[Service]` с `ExecStart`. Путь — полный: у systemd нет твоего `PATH`.

## Проверить юнит до запуска

`systemd-analyze verify` ловит опечатки, которые systemd молча проигнорировал бы. Юнит с двумя
ошибками — относительный путь и `Restrt` вместо `Restart`:

    $ systemd-analyze verify ./bad.service
    /tmp/tmp.ubP49i3NpU/bad.service:6: Unknown key 'Restrt' in section [Service], ignoring.
    bad.service: Command tick is not executable: No such file or directory

## Новый или изменённый юнит

systemd читает юниты в память. Новый файл `start` найдёт сам, а **изменённый** — нет: systemd
работает по старой версии и предупреждает:

    Warning: The unit file, source configuration file or drop-ins of mytest-tick.service changed on disk. Run 'systemctl --user daemon-reload' to reload units.

После правки юнита — `sudo systemctl daemon-reload`, потом `restart`.

## [Install] и enable

`enable` не трогает работающую службу, а записывает, **когда** её запускать. Это «когда» —
секция `[Install]`. Без неё enable отказывается:

    $ systemctl --user enable mytest-tick
    The unit files have no installation config (WantedBy=, RequiredBy=, UpheldBy=,
    Also=, or Alias= settings in the [Install] section, and DefaultInstance= for
    template units). This means they are not meant to be enabled or disabled using systemctl.

С секцией — создаёт ссылку в каталоге `….target.wants/`:

    $ systemctl --user enable mytest-tick
    Created symlink '/home/anya/.config/systemd/user/default.target.wants/mytest-tick.service' → '/home/anya/.config/systemd/user/mytest-tick.service'.

**target** — точка загрузки. Для системных служб это почти всегда `multi-user.target` — «система
загрузилась и готова к работе», и ссылка ляжет в `/etc/systemd/system/multi-user.target.wants/`.
(У пользовательских `--user` служб своя цель — `default.target`.)

## Restart= — служба, которая встаёт сама

По умолчанию systemd только записывает, что служба умерла. Чтобы поднимал снова — `Restart=`:

    Restart=always        всегда, как бы ни завершилась
    Restart=on-failure    только при ошибке или смерти от сигнала, не при выходе с кодом 0

Служба с `Restart=always` и `RestartSec=2`, её главный процесс убили через KILL:

    $ journalctl --user -u mytest-tick --no-pager
    Nov 04 02:20:52 anya tick[409581]: тик
    Nov 04 02:20:57 anya tick[409581]: тик
    Nov 04 02:21:00 anya systemd[2629]: mytest-tick.service: Main process exited, code=killed, status=9/KILL
    Nov 04 02:21:00 anya systemd[2629]: mytest-tick.service: Failed with result 'signal'.
    Nov 04 02:21:02 anya systemd[2629]: mytest-tick.service: Scheduled restart job, restart counter is at 1.
    Nov 04 02:21:02 anya systemd[2629]: Started mytest-tick.service - [systemd-run] /tmp/tmp.ubP49i3NpU/tick.
    Nov 04 02:21:02 anya tick[410561]: тик
    $ systemctl --user show -p MainPID -p NRestarts mytest-tick
    MainPID=410561
    NRestarts=1

Новый PID, счётчик перезапусков — 1. Метки времени и имя в квадратных скобках добавил systemd:
скрипт печатал только «тик». Остановить такую службу насовсем — `systemctl stop`: его systemd
не считает падением и не перезапускает.

## Попробовать без root

Всё то же есть у пользователя: `systemctl --user`, `journalctl --user`, юниты в
`~/.config/systemd/user/`. А `systemd-run --user` запускает команду временной службой, без
файла: `systemd-run --user --unit=demo -p Restart=always ./tick`.

## Источники

- [man systemd.service (man7.org)](https://man7.org/linux/man-pages/man5/systemd.service.5.html) —
  `ExecStart=`, `Restart=`, `User=`.
- [man systemd.unit (man7.org)](https://man7.org/linux/man-pages/man5/systemd.unit.5.html) —
  `[Unit]`, `[Install]`, `WantedBy=`.
- [man systemd-run (man7.org)](https://man7.org/linux/man-pages/man1/systemd-run.1.html) —
  временные службы.
- [systemd — ArchWiki (рус.)](https://wiki.archlinux.org/title/Systemd_(Русский)) — как писать
  юниты, по-русски.
- [systemd.service — freedesktop.org](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html) —
  официальная документация, самая свежая.
