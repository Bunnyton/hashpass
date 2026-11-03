---
tags: процессы, службы, systemd, сеть
---
# Службы: systemctl, journalctl, порты и /etc/hosts

«Сайт не открывается» — самая частая жалоба, с которой приходят к администратору. Причин
обычно три, и проверяют их по порядку: **имя** превращается в адрес? **служба** запущена? **порт**
не занят кем-то другим? Здесь — инструменты для каждого шага.

## Что такое служба

**Служба** (service) — программа, которая работает в фоне, пока включён компьютер: веб-сервер,
база данных, SSH. Терминала у неё нет, и [фоновые задания](/web/wiki/bunnyton/jobs) ей не
подходят — те умирают вместе с терминалом. Службами управляет **systemd**, PID 1:

1. при загрузке запускает те, что положено;
2. знает их PID и складывает их вывод в журнал;
3. может перезапустить упавшую;
4. при выключении останавливает по порядку.

## Юнит — описание службы

Как запускать, systemd читает из **юнит-файла**. Посмотреть юнит любой службы:

    $ systemctl cat cron
    # /usr/lib/systemd/system/cron.service
    [Unit]
    Description=Regular background program processing daemon
    …
    [Service]
    ExecStart=/usr/sbin/cron -f $EXTRA_OPTS
    Restart=on-failure
    …
    [Install]
    WantedBy=multi-user.target

Юниты пакетов лежат в `/usr/lib/systemd/system/` (он же `/lib/…`), юниты администратора — в
`/etc/systemd/system/`, и они главнее. Имя юнита — имя файла; `.service` в командах можно не
писать. Как написать свой — в [задании my-service](/web/wiki/bunnyton/my-service).

## systemctl — пульт

    systemctl status cron       жива ли, PID, включена ли, последние строки журнала
    systemctl start cron        запустить сейчас          stop — остановить сейчас
    systemctl restart cron      остановить и запустить
    systemctl enable cron       запускать при загрузке    disable — не запускать
    systemctl is-active cron    одно слово: active / inactive / failed
    systemctl is-enabled cron   одно слово: enabled / disabled / static
    systemctl list-units --type=service          что работает сейчас

Смотреть может кто угодно, менять — только администратор, через `sudo`.
    $ systemctl status cron
    ● cron.service - Regular background program processing daemon
         Loaded: loaded (/usr/lib/systemd/system/cron.service; enabled; preset: enabled)
         Active: active (running) since Mon 2026-11-02 17:49:52 MSK; 1 day 8h ago
     Invocation: 78eabbec028a4f83bb56b4eebf33b2bb
           Docs: man:cron(8)
       Main PID: 2046 (cron)
     …
         CGroup: /system.slice/cron.service
                 └─2046 /usr/sbin/cron -f

Две главные строки: **Loaded** — где юнит и автозапуск, **Active** — работает ли сейчас.

**start/stop — про «сейчас», enable/disable — про «после перезагрузки».** Это независимые
вещи: служба может работать и не быть в автозапуске — до первой перезагрузки. Классическая
ошибка: запустил, проверил, ушёл домой, а ночью сервер перезагрузился. Для краткости есть
`enable --now` и `disable --now` — оба действия сразу.

## journalctl — почему не запустилась

Служба упала — ответ почти всегда в её журнале. Пример — пользовательская служба (`--user`,
без root; у системных всё так же, только без `--user`):

    $ systemctl --user status mytest-web
    × mytest-web.service - [systemd-run] /usr/bin/busybox httpd -f -p 127.0.0.1:18471 …
         Active: failed (Result: exit-code) since Wed 2026-11-04 02:29:57 MSK; 23ms ago
       Main PID: 434481 (code=exited, status=1/FAILURE)
    $ journalctl --user -u mytest-web
    Nov 04 02:29:57 anya systemd[2629]: Started mytest-web.service - [systemd-run] …
    Nov 04 02:29:57 anya busybox[434481]: httpd: bind: Address already in use
    Nov 04 02:29:57 anya systemd[2629]: mytest-web.service: Main process exited, code=exited, status=1/FAILURE
    Nov 04 02:29:57 anya systemd[2629]: mytest-web.service: Failed with result 'exit-code'.

`status` сказал «failed», а журнал — **почему**. Ключи: `-e` — сразу в конец, `-f` —
следить вживую, `-b` — с последней загрузки, `--since "10 min ago"`. Системные журналы читают
root и группа `adm`/`systemd-journal` — остальным journalctl так и пишет:
`You are currently not seeing messages from other users and the system`.

## Порт занят

Сетевая программа слушает **порт** (1–65535): SSH — 22, веб — 80 и 443. Один порт на одном
адресе может держать только одна программа; вторая не запустится:

    $ busybox httpd -f -p 127.0.0.1:18471 -h www
    httpd: bind: Address already in use

Кто держит порт:

    $ ss -ltnp sport = :18471
    State  Recv-Q Send-Q Local Address:Port  Peer Address:PortProcess
    LISTEN 0      9          127.0.0.1:18471      0.0.0.0:*    users:(("busybox",pid=408729,fd=3))
    $ fuser 18471/tcp
    18471/tcp:           408729

`ss -ltnp` — кто слушает TCP (listen, tcp, numeric, process); чужие процессы видит только root.
Нашёл PID, а это служба? — `systemctl status PID` скажет, какая.

## Имена и /etc/hosts

Прежде чем подключиться, имя превращают в адрес. Система сначала смотрит свою записную книжку —
**`/etc/hosts`**, потом спрашивает DNS. Порядок задан в `/etc/nsswitch.conf`:

    $ grep '^hosts' /etc/nsswitch.conf
    hosts:          files mdns4_minimal [NOTFOUND=return] mymachines dns

`files` — это и есть `/etc/hosts`. Формат простой — адрес и имена через пробел:

    127.0.0.1    localhost
    10.0.0.5     db.local backup.local

`127.0.0.1` — «этот компьютер». Файл принадлежит root. Проверить, во что превращается имя:

    $ getent hosts localhost
    ::1             localhost ip6-localhost ip6-loopback

## Читай ошибку curl

curl сам говорит, на каком шаге сломалось:

    $ curl http://nosuch.corp:18471/
    curl: (6) Could not resolve host: nosuch.corp
    $ curl http://127.0.0.1:18471/
    curl: (7) Failed to connect to 127.0.0.1 port 18471 after 0 ms: Could not connect to server

- **(6) Could not resolve host** — имя не знает никто: смотри `/etc/hosts` и DNS;
- **(7) Failed to connect** (или `Connection refused`) — на порту никто не слушает;
- ответ пришёл, но **не тот** — на порту сидит другая программа.

## Источники

- [man systemctl (man7.org)](https://man7.org/linux/man-pages/man1/systemctl.1.html) — все
  команды пульта.
- [man journalctl (man7.org)](https://man7.org/linux/man-pages/man1/journalctl.1.html) —
  фильтры журнала.
- [systemd — ArchWiki (рус.)](https://wiki.archlinux.org/title/Systemd_(Русский)) — systemd
  по-русски, с примерами.
- [man ss (man7.org)](https://man7.org/linux/man-pages/man8/ss.8.html) — кто слушает порты.
- [man hosts (man7.org)](https://man7.org/linux/man-pages/man5/hosts.5.html) и
  [hosts — Википедия](https://ru.wikipedia.org/wiki/Hosts) — формат и история `/etc/hosts`.
