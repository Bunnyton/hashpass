---
tags: основы, пользователи, whoami, id
---
# Кто я в системе: whoami, id, groups

Linux — система многопользовательская: на одной машине одновременно живут люди, службы и сам
администратор `root`. У каждого — своё имя, свои файлы и свои права. Поэтому первый вопрос в
незнакомой консоли — «кто я здесь?».

## Как устроена консоль

Ты пишешь команду и жмёшь Enter — система отвечает текстом. Слева от курсора — **приглашение**
(prompt): обычно в нём имя пользователя, имя машины и текущий каталог, например
`student@hashpass:~$`. Знак `$` в конце — обычный пользователь, `#` — `root`.

В консоли hashpass:

- подсказки приходят неохотно, после нескольких твоих попыток — так задумано;
- читай вывод команд: там почти всегда уже написано, что не так;
- `readme` покажет теорию задания ещё раз, `exit` — выход.

## whoami — имя пользователя

    $ whoami
    anya

Одно слово — имя, под которым ты сейчас работаешь (здесь вывод с машины автора wiki; у тебя
будет своё). Название читается как «who am I».

## id — подробнее

`id` рассказывает больше: числовой номер пользователя (**uid**), основную группу (**gid**) и все
группы, в которых ты состоишь:

    $ id
    uid=1000(anya) gid=1000(anya) groups=1000(anya),24(cdrom),25(floppy),27(sudo),29(audio),30(dip),44(video),46(plugdev),100(users),101(netdev),102(scanner),106(bluetooth),108(lpadmin),984(docker),10000(hashpass)

Ключи сужают ответ: `-u` — только номер, `-n` — имя вместо номера:

    $ id -un
    anya

Для системы ты на самом деле **число**: файлы помнят uid владельца, а имя подставляется из
`/etc/passwd`. У `root` uid всегда 0.

## groups — в каких ты группах

Группы — способ выдать права сразу многим: всем из группы `audio` можно звук, из `sudo` —
команды от имени администратора.

    $ groups
    anya cdrom floppy sudo audio dip video plugdev users netdev scanner bluetooth lpadmin docker hashpass

## $USER — то же из переменной

Оболочка хранит имя ещё и в переменной окружения `USER`:

    $ echo $USER
    anya

Переменную можно подменить, так что для честного ответа надёжнее `whoami` или `id`.

## Где пригодится

- после `sudo -i` или `su` — проверить, под кем ты теперь (`root` или нет);
- скрипт, который нельзя запускать от root, сначала смотрит `id -u`;
- «Permission denied» — первым делом `whoami` и `ls -l`: чей файл и кто ты.

Дальше — [первые шаги](/web/wiki/bunnyton/first-steps) и [первые команды](/web/wiki/bunnyton/first-commands).

## Источники

- [`man 1 whoami`](https://man7.org/linux/man-pages/man1/whoami.1.html)
- [`man 1 id`](https://man7.org/linux/man-pages/man1/id.1.html) — все ключи id.
- [`man 1 groups`](https://man7.org/linux/man-pages/man1/groups.1.html)
- [The Linux command line for beginners — Ubuntu](https://ubuntu.com/tutorials/command-line-for-beginners)
  — пошаговое знакомство с терминалом.
- [Learning the Shell — LinuxCommand.org](https://linuxcommand.org/lc3_learning_the_shell.php) —
  классический учебник по оболочке.
