---
tags: bash, systemd, службы, trap, EnvironmentFile, скрипты
---
# Служба на своём bash-скрипте

Служба — это программа, которая работает постоянно под присмотром systemd. Программой может быть
и bash-скрипт, но тогда к нему больше требований, чем к скрипту «запустил и забыл»: он работает
без терминала, от другого пользователя, с окружением от systemd и должен корректно
останавливаться.

## Из чего состоит

1. **Скрипт** — исполняемый файл с бесконечным циклом, например `/usr/local/bin/sorter`.
2. **Юнит** — `/etc/systemd/system/sorter.service`:

       [Unit]
       Description=sorter — разбирает входящие файлы

       [Service]
       ExecStart=/usr/local/bin/sorter
       User=student
       EnvironmentFile=-/etc/default/sorter
       Restart=on-failure

       [Install]
       WantedBy=multi-user.target

3. Управление: `sudo systemctl daemon-reload` после правки юнита, `start`/`stop`/`restart`,
   `enable` — автозапуск, `journalctl -u sorter` — журнал (всё, что скрипт печатает).

`ExecStart` — путь к файлу, а не однострочник `bash -c '…'`: файл можно проверить `shellcheck`,
запустить руками и поправить, не трогая юнит.

## case — решения по шаблону

```
$ for f in фото.jpg отчёт.pdf песня.mp3; do case $f in *.jpg|*.png) echo "$f → images" ;; *.pdf|*.txt) echo "$f → docs" ;; *) echo "$f → other" ;; esac; done
фото.jpg → images
отчёт.pdf → docs
песня.mp3 → other
```

Ветки проверяются по порядку, срабатывает первая подходящая; `*)` — всё остальное.

## User= — не от root

По умолчанию служба работает от root. Если ей root не нужен — `User=имя`: ошибка в скрипте
тогда сломает только то, что доступно этому пользователю, а файлы, которые служба создаёт,
принадлежат ему. Код `217/USER` в `systemctl status` — такого пользователя нет.

## Настройки — в окружении: EnvironmentFile

Зашитый в скрипт путь — это правка кода при каждом переезде. Службы Debian берут настройки из
`/etc/default/<имя>`:

    $ cat /etc/default/sorter
    INBOX=/home/student/drop

- `EnvironmentFile=/etc/default/sorter` в юните — systemd прочитает строки `ИМЯ=значение` и
  положит их в окружение службы (без `export`, без подстановок `$`);
- `-` перед путём — «файла может не быть»;
- `Environment=ИМЯ=значение` — одна переменная прямо в юните.

В скрипте — значение по умолчанию на случай, если переменной нет:

```
$ unset INBOX; echo ${INBOX:-/home/student/inbox}; INBOX=/srv/drop; echo ${INBOX:-/home/student/inbox}
/home/student/inbox
/srv/drop
```

systemd читает файл при запуске службы: поменял — `restart`.

## trap — корректная остановка

`systemctl stop` посылает **TERM** всем процессам службы, ждёт (по умолчанию до 90 секунд) и
только потом добивает **KILL**. Без обработчика bash от TERM просто умирает. С `trap` — успевает
закончить дела:

```
$ cat tr.sh
#!/bin/bash
count=0
trap 'echo "остановлен, кругов: $count"; exit 0' TERM
while true; do count=$((count + 1)); sleep 1; done
$ ./tr.sh & sleep 3.5; kill -TERM $!; wait
остановлен, кругов: 4
```

Тонкость: bash выполняет обработчик, только когда закончится текущая команда переднего плана.
`kill` одному bash ждёт конца `sleep`. systemd же бьёт по всей группе процессов службы — `sleep`
умирает сразу, и в журнале это видно:

    Nov 04 03:37:14 hashpass sorter[3050]: Terminated
    Nov 04 03:37:14 hashpass sorter[3050]: sorter: остановлен, разобрано 0

Для уборки при любом выходе — `trap '…' EXIT` (временные файлы, блокировки).

## Чек-лист скрипта-службы

- `#!/bin/bash` и `set -euo pipefail` — молчаливая ошибка в службе видна только по последствиям;
- пути — полные или из окружения: у службы нет твоего `PATH`, `~` и текущего каталога;
- `sleep` в цикле — иначе скрипт съест процессор;
- пустой шаблон (`"$dir"/*` в пустом каталоге) — `[ -e "$f" ] || continue`;
- вывод — в stdout: его сохранит journald с меткой времени;
- `trap` на TERM, если есть что дописать или убрать.

## Источники

- `man systemd.service` — [на man7.org](https://man7.org/linux/man-pages/man5/systemd.service.5.html):
  `ExecStart`, `Restart`, `TimeoutStopSec`.
- `man systemd.exec` — [на man7.org](https://man7.org/linux/man-pages/man5/systemd.exec.5.html):
  `User`, `Environment`, `EnvironmentFile`.
- `man systemd.kill` — [на man7.org](https://man7.org/linux/man-pages/man5/systemd.kill.5.html):
  как именно останавливают службу.
- [SignalTrap — Greg's Wiki](https://mywiki.wooledge.org/SignalTrap) — сигналы и `trap` в bash.
- [bash-handbook](https://github.com/denysdovhan/bash-handbook),
  [bash-scripts-by-example](https://github.com/cheatsnake/bash-scripts-by-example/blob/master/README_RUS.md),
  [awesome-bash](https://github.com/awesome-lists/awesome-bash).
