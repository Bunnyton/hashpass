---
tags: права, группы, chgrp, chown, файлы
---
# Владелец, группа и chgrp

У каждого файла два хозяина: **владелец** (один пользователь) и **группа** (сразу много
пользователей). Права в `ls -l` разбиты на три тройки как раз под них: владельцу, группе,
остальным. Про сами `rwx` — в [wiki про chmod](/web/wiki/bunnyton/chmod-basics).

## Твои группы

    $ groups
    anya cdrom floppy sudo audio dip video plugdev users netdev scanner bluetooth lpadmin docker hashpass
    $ id
    uid=1000(anya) gid=1000(anya) groups=1000(anya),24(cdrom),25(floppy),27(sudo),29(audio),...

`id` показывает ещё и номера. Первая группа (`gid=`) — основная: её получают все новые
файлы. При создании пользователя Debian заводит ему одноимённую группу, поэтому в `ls -l`
так часто видно `anya anya`.

Группы записаны в `/etc/group` — читать его можно всем:

    $ getent group users sudo
    users:x:100:anya
    sudo:x:27:anya

Формат: имя, пароль (не используется), номер, участники через запятую. Так и выдают доступ
сразу многим: всех бухгалтеров — в группу `buh`, а файлам отчётов — группу `buh` и права
`rw-` для группы.

## Кому что видно

    $ ls -l /etc/shadow
    -rw-r----- 1 root shadow 1153 Oct 28 08:17 /etc/shadow
    $ cat /etc/shadow
    cat: /etc/shadow: Permission denied

Владелец root может читать и писать, группа `shadow` — только читать, остальные — ничего.
Ты не root и не в группе `shadow`, значит, для тебя действует третья тройка: `---`.

Система выбирает **одну** тройку, сверху вниз: ты владелец → тройка владельца; иначе
состоишь в группе файла → тройка группы; иначе → остальные.

## chgrp — сменить группу

    $ ls -l report.txt
    -rw-r----- 1 anya anya 31 Nov  4 02:20 report.txt
    $ chgrp users report.txt
    $ ls -l report.txt
    -rw-r----- 1 anya users 31 Nov  4 02:20 report.txt

Теперь отчёт прочитают все из группы `users`. Правила у chgrp строгие:

- менять группу может только **владелец** файла (и root);
- владелец может отдать файл только той группе, в которой **сам состоит**:

      $ chgrp root report.txt
      chgrp: changing group of 'report.txt': Operation not permitted
      $ chgrp nosuchgroup report.txt
      chgrp: invalid group: ‘nosuchgroup’

- root может всё: любую группу любому файлу.

Обрати внимание на разницу ошибок: `Permission denied` — не пустили к содержимому (права),
`Operation not permitted` — такое действие тебе не положено вообще (кто ты такой, чтобы
менять чужое).

## chown — сменить владельца

    $ chown root report.txt
    chown: changing ownership of 'report.txt': Operation not permitted

Отдать файл другому пользователю может только root — иначе можно было бы подкидывать файлы
кому угодно. `chown` умеет и группу сразу:

    chown пользователь:группа файл    # обоих
    chown :группа файл                # только группу — как chgrp

## Номера вместо имён

Внутри файловой системы хранятся не имена, а номера. `ls -n` показывает их как есть:

    $ ls -ln report.txt
    -rw-r----- 1 1000 100 31 Nov  4 02:20 report.txt

Если в `ls -l` вместо имени видно число, значит, такого пользователя или группы на этой
машине нет — типично для файлов, принесённых с другого компьютера или из архива.

## Общий каталог для команды

Бит setgid на каталоге (`s` на месте `x` группы) — новые файлы внутри получают группу
каталога, а не основную группу создателя:

    $ mkdir shared; chgrp users shared; chmod 2775 shared
    $ touch shared/x; ls -ld shared; ls -l shared
    drwxrwsr-x 2 anya users 60 Nov  4 02:20 shared
    total 0
    -rw-rw-r-- 1 anya users 0 Nov  4 02:20 x

## Где это пригодится

- общий каталог проекта для нескольких людей;
- доступ к устройствам и службам: группы `docker`, `audio`, `video`, `dialout` — добавили
  в группу, и пользователь получил доступ (после нового входа в систему);
- веб-сервер работает от `www-data` и читает файлы сайта через группу.

## Источники

- [chgrp(1)](https://man7.org/linux/man-pages/man1/chgrp.1.html) и
  [chown(1)](https://man7.org/linux/man-pages/man1/chown.1.html) на man7.org.
- [group(5)](https://man7.org/linux/man-pages/man5/group.5.html) — формат `/etc/group`.
- [Пользователи и группы — ArchWiki (русский)](https://wiki.archlinux.org/title/Users_and_groups_(Русский))
  — как всё устроено и как управлять.
- [SystemGroups — Debian Wiki](https://wiki.debian.org/SystemGroups) — какие группы что дают в
  Debian.
