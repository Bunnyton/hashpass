---
tags: ядро, драйверы, устройства, dev, misc
---
# Символьные устройства

В Linux устройство — это файл в `/dev`. Читаешь его — данные отдаёт не диск, а драйвер.
**Символьное** (character) устройство отдаёт байты потоком: терминал, `/dev/null`,
`/dev/urandom`. **Блочное** — кусками с произвольным доступом: диски.

    $ ls -l /dev/null /dev/zero /dev/urandom /dev/tty
    crw-rw-rw- 1 root root 1, 3 Nov  2 17:49 /dev/null
    crw-rw-rw- 1 root tty  5, 0 Nov  4 02:20 /dev/tty
    crw-rw-rw- 1 root root 1, 9 Nov  2 17:49 /dev/urandom
    crw-rw-rw- 1 root root 1, 5 Nov  2 17:49 /dev/zero
    $ ls -l /dev/nvme0n1
    brw-rw---- 1 root disk 259, 0 Nov  2 17:49 /dev/nvme0n1

Первая буква: `c` — символьное, `b` — блочное. Вместо размера — два числа: **major** (номер
драйвера) и **minor** (какое из его устройств). `/dev/null` и `/dev/zero` — один драйвер
`mem` (1), разные устройства (3 и 5). Какие драйверы заняли какие номера, видно в
`/proc/devices`:

    $ head -5 /proc/devices
    Character devices:
      1 mem
      4 /dev/vc/0
      4 tty
      4 ttyS

## misc — самый простой путь

Свой номер драйверу заводить не обязательно: есть общий драйвер **misc** с major 10. Он
выдаёт устройству свободный minor и сам создаёт файл в `/dev`:

    $ head -3 /proc/misc
    200 tun
    223 uinput
    262 vsock
    $ ls -l /dev/fuse /dev/loop-control
    crw-rw-rw- 1 root root 10, 229 Nov  2 17:49 /dev/fuse
    crw-rw---- 1 root disk 10, 237 Nov  2 17:49 /dev/loop-control

Помнишь `alias: char-major-10-237` у модуля `loop`? Это и есть `/dev/loop-control`.

## Что драйвер делает при read и write

Какие операции умеет файл устройства, драйвер говорит таблицей `struct file_operations`:
`.read`, `.write`, `.open` и другие. Когда программа зовёт `read()`, ядро зовёт функцию
драйвера и передаёт ей буфер программы, сколько байт просят и **смещение** — сколько уже
прочитано. Правила игры:

- вернуть нужно, **сколько байт** отдал; `0` значит «конец файла» — `cat` читает, пока не
  получит 0;
- память программы — не память ядра: писать в неё напрямую нельзя, копируют
  `copy_to_user()`, а принимают данные `copy_from_user()`;
- `write` возвращает, сколько байт **принял**; вернёшь меньше — программа допишет остаток
  ещё одним вызовом.

## Источники

- [The Linux Kernel Module Programming Guide](https://sysprog21.github.io/lkmpg/) — свежий
  учебник по модулям: от hello до символьных устройств.
- [Building External Modules](https://docs.kernel.org/kbuild/modules.html) — как Kbuild
  собирает внешние модули.
- [Linux Kernel Labs: Character device drivers](https://linux-kernel-labs.github.io/refs/heads/master/labs/device_drivers.html) —
  лабораторная про major/minor, file_operations, copy_to_user.
- [Linux allocated devices](https://docs.kernel.org/admin-guide/devices.html) — какие номера
  за какими устройствами закреплены.
- [insmod](https://man7.org/linux/man-pages/man8/insmod.8.html), [lsmod](https://man7.org/linux/man-pages/man8/lsmod.8.html), [modinfo](https://man7.org/linux/man-pages/man8/modinfo.8.html) — справка.
