---
tags: tmp, tmpfs, tmpfiles, перезагрузка, systemd
---
# /tmp, /var/tmp и перезагрузка

Программам нужно место «на минутку»: распаковать архив, собрать промежуточный файл, положить сокет.
Для этого есть два общих каталога. Писать в них может любой, а удалять — только своё (это «липкий»
бит `t` в правах):

    $ ls -ld /tmp /var/tmp
    drwxrwxrwt 2 root root   40 Nov  4 03:09 /tmp
    drwxrwxrwt 2 root root 4096 Jul  4 12:05 /var/tmp

| | `/tmp` | `/var/tmp` |
|---|---|---|
| где живёт | часто в оперативной памяти (tmpfs) | на диске |
| после перезагрузки | пусто | на месте |
| чистится по возрасту | через 10 дней | через 30 дней |
| для чего | совсем временное, мелкое | временное, но подольше: загрузки, сборки |

## Где живёт каталог: df и findmnt

    $ df -h /tmp
    Filesystem      Size  Used Avail Use% Mounted on
    tmpfs           1.6G     0  1.6G   0% /tmp
    $ findmnt /tmp
    TARGET SOURCE FSTYPE OPTIONS
    /tmp   tmpfs  tmpfs  rw,nosuid,nodev,size=1587948k,nr_inodes=409600,inode64

**tmpfs** — файловая система в оперативной памяти: очень быстрая, а при выключении всё в ней
исчезает. Размер — по умолчанию половина памяти, но память занимают только реально записанные
файлы. В Debian с версии 13 `/tmp` — tmpfs по умолчанию; на старых системах это просто каталог на
диске, который очищают при загрузке.

## Кто чистит: systemd-tmpfiles

Чистит не cron и не человек, а **systemd-tmpfiles** по правилам из `tmpfiles.d`:

- `/usr/lib/tmpfiles.d/*.conf` — правила пакетов;
- `/etc/tmpfiles.d/*.conf` — правила администратора, главнее (файл с тем же именем заменяет системный).

При загрузке он создаёт описанные каталоги и файлы, а раз в день (таймер
`systemd-tmpfiles-clean.timer`) удаляет то, что старше заданного возраста:

    $ grep -r /var/tmp /usr/lib/tmpfiles.d
    /usr/lib/tmpfiles.d/systemd-tmp.conf:x /var/tmp/systemd-private-%b-*
    /usr/lib/tmpfiles.d/systemd-tmp.conf:X /var/tmp/systemd-private-%b-*/tmp
    /usr/lib/tmpfiles.d/systemd-tmp.conf:R! /var/tmp/systemd-private-*
    /usr/lib/tmpfiles.d/tmp.conf:q /var/tmp 1777 root root 30d

## Формат правила

    тип   путь           права  владелец  группа  возраст
    d     /run/myapp     0750   myapp     myapp   -
    q     /var/tmp       1777   root      root    30d

Самые нужные типы: `d` — создать каталог (и чистить по возрасту, если он указан), `D` — то же, но
очищать при каждой загрузке, `f` — создать файл, `L` — ссылку, `x` — не трогать при очистке, `q` —
каталог-подтом btrfs или обычный каталог. Применить правило без перезагрузки:

    sudo systemd-tmpfiles --create /etc/tmpfiles.d/myapp.conf

Так пакеты заводят каталоги в `/run` (он тоже tmpfs и пустеет при каждой загрузке): служба
стартует, а её каталог уже на месте и с правильным владельцем.

## Что куда класть

- результат, который нужен завтра, — в домашний каталог или `/var/lib/<программа>`;
- кэш, который можно пересоздать, — `~/.cache` или `/var/cache`;
- промежуточное на время работы программы — `/tmp`, а большое — `/var/tmp`;
- имя временного файла лучше брать у `mktemp`: он придумает уникальное и не даст подсунуть чужой файл.

## Источники

- `man 5 tmpfiles.d` — [на man7.org](https://man7.org/linux/man-pages/man5/tmpfiles.d.5.html): типы строк и возраст.
- `man 8 systemd-tmpfiles` — [на man7.org](https://man7.org/linux/man-pages/man8/systemd-tmpfiles.8.html).
- `man 5 tmpfs` — [на man7.org](https://man7.org/linux/man-pages/man5/tmpfs.5.html): что такое tmpfs.
- `man 1 df` — [на man7.org](https://man7.org/linux/man-pages/man1/df.1.html).
- [Filesystem Hierarchy Standard 3.0](https://refspecs.linuxfoundation.org/FHS_3.0/fhs/index.html) — разделы /tmp и /var/tmp.
