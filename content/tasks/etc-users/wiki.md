---
tags: пользователи, группы, etc, useradd, skel, sudo
---
# Учётки — это строки в /etc

Пользователь в Linux — это не каталог и не программа, а несколько строк в текстовых файлах:

| Файл | Что хранит | Кто читает |
|---|---|---|
| `/etc/passwd` | имя, номер (UID), основная группа (GID), домашний каталог, оболочка | все |
| `/etc/shadow` | хеш пароля, срок действия | только root |
| `/etc/group` | группы и кто в них состоит | все |
| `/etc/gshadow` | пароли групп (почти не используются) | только root |
| `/etc/skel/` | шаблон домашнего каталога нового пользователя | — |

Строка `/etc/passwd`:

    student:x:1000:1000::/home/student:/bin/bash

Строка `/etc/group` — имя группы, `x`, номер, участники через запятую:

    sudo:x:27:student

## useradd — завести пользователя

Писать эти строки руками можно, но легко ошибиться. Их дописывает `useradd` (запускается от root):

    sudo useradd intern            только учётка: строки в passwd, shadow, group
    sudo useradd -m intern         и домашний каталог /home/intern
    sudo useradd -m -s /bin/bash -G sudo,adm intern    оболочка и дополнительные группы сразу

Без `-m` дома нет: войти можно, но `cd ~` скажет «No such file or directory». Учётка уже есть,
а дома нет — проще удалить и завести заново:

    sudo userdel intern            удалить учётку
    sudo userdel -r intern         вместе с домашним каталогом и почтовым ящиком

В Debian есть ещё `adduser` — обёртка вокруг `useradd`, которая сама создаёт дом и спрашивает пароль.

## /etc/skel — откуда берутся .bashrc и .profile

`useradd -m` не создаёт пустой каталог, а **копирует** в него содержимое `/etc/skel`:

    $ ls -a /etc/skel
    .  ..  .bash_logout  .bashrc  .profile

Положил туда файл — его получит каждый новый пользователь, но не те, кто уже есть: копирование
делается один раз, при создании.

    $ sudo cp ~/ПАМЯТКА.txt /etc/skel/
    $ sudo useradd -m intern2
    $ sudo ls /home/intern2
    ПАМЯТКА.txt

Так раздают общий `.vimrc`, настройки оболочки, памятки. Чтобы чужой домашний каталог посмотреть,
нужен `sudo`: каталог новичка закрыт от остальных.

## Группы и sudo

Права часто раздают не человеку, а группе. В Debian `sudo` разрешён группе `sudo` — так написано в
`/etc/sudoers` (`%sudo ALL=(ALL:ALL) ALL`). Значит, дать человеку sudo — добавить его в группу:

    $ id intern
    uid=1001(intern) gid=1001(intern) groups=1001(intern)
    $ sudo usermod -aG sudo intern
    $ id intern
    uid=1001(intern) gid=1001(intern) groups=1001(intern),27(sudo)

`-G` — список дополнительных групп, `-a` — **добавить** к ним, а не заменить. Без `-a` человек
вылетит из всех остальных групп — частая ошибка. Изменение вступает в силу при следующем входе
пользователя.

Другие полезные группы Debian: `adm` — читать журналы в `/var/log`, `systemd-journal` — читать весь
журнал systemd, `docker` — управлять Docker (это почти как root).

Править `/etc/passwd` и `/etc/group` руками можно, но безопаснее через `sudo vipw` и `sudo vigr`:
они блокируют файл, пока ты его правишь, и проверяют, что ничего не сломалось.

## Источники

- `man 8 useradd` — [на man7.org](https://man7.org/linux/man-pages/man8/useradd.8.html): ключи и про /etc/skel.
- `man 8 usermod` — [на man7.org](https://man7.org/linux/man-pages/man8/usermod.8.html): `-a` и `-G`.
- `man 5 passwd` — [на man7.org](https://man7.org/linux/man-pages/man5/passwd.5.html), `man 5 group` — [на man7.org](https://man7.org/linux/man-pages/man5/group.5.html).
- [SystemGroups — Debian Wiki](https://wiki.debian.org/SystemGroups) — какие группы что дают в Debian.
