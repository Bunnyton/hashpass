---
tags: ядро, модули, драйверы, устройства
---
# Модули ядра и символьные устройства

**Ядро** — программа, которая управляет железом, памятью и процессами. **Модуль** — кусок
кода, который подгружается в уже работающее ядро без перезагрузки. Так приходят почти все
драйверы: сетевые карты, файловые системы, USB. Здесь — как модули устроены, как их собирают
и как драйвер превращается в файл в `/dev`.

## Модули, которые уже работают

Список загруженных — `lsmod` (он читает `/proc/modules`):

    $ lsmod | head -6
    Module                  Size  Used by
    nft_masq               12288  0
    nft_ct                 28672  1
    tcp_diag               12288  0
    udp_diag               12288  0
    inet_diag              28672  2 tcp_diag,udp_diag

Колонка `Used by` — кто от модуля зависит: пока счётчик не 0, выгрузить его нельзя. Всё о
модуле на диске — `modinfo`:

    $ modinfo loop
    filename:       /lib/modules/6.12.105+deb13-amd64/kernel/drivers/block/loop.ko.xz
    alias:          devname:loop-control
    alias:          char-major-10-237
    license:        GPL
    description:    Loopback device support
    intree:         Y
    name:           loop
    vermagic:       6.12.105+deb13-amd64 SMP preempt mod_unload modversions
    ...
    parm:           max_loop:Maximum number of loop devices

Обрати внимание на `vermagic`: модуль собран под **конкретную версию** ядра. Под другую
версию ядро его просто не примет.

## Чьё ядро и под какое собирать

`uname -r` называет ядро, на котором ты сейчас работаешь. Готовые модули и всё для сборки
лежат по версиям в `/lib/modules/<версия>/`, а заголовки для сборки — в
`/lib/modules/<версия>/build`. Их может и не быть — тогда сборщику не за что взяться:

    $ uname -r
    6.12.105+deb13-amd64
    $ ls /lib/modules/$(uname -r)/build
    ls: cannot access '/lib/modules/6.12.105+deb13-amd64/build': No such file or directory

Правило одно: модуль собирают под **то ядро, где он будет жить**. Ядро, на котором работает
твой компьютер, и ядро виртуальной машины — разные ядра, даже если версии похожи. А опыты со
своими модулями ставят в ВМ: ошибка в модуле роняет не программу, а всё ядро целиком.

## Скелет модуля

У модуля нет `main`. Есть функция, которую ядро зовёт при загрузке (`module_init`), и функция
для выгрузки (`module_exit`). Пишет модуль не в терминал, а в **журнал ядра** — `pr_info()`;
читают его `dmesg` (обычно только root). `MODULE_LICENSE("GPL")` обязателен: без него
свежий Kbuild модуль не соберёт, а ядру лицензия говорит, какие его функции модулю можно звать.

Собирает модули не `gcc` напрямую, а система сборки ядра **Kbuild**. Ей нужен `Makefile`
со списком модулей `obj-m += имя.o` (имя объектного файла, не `.c`) и команда:

    make -C <каталог сборки ядра> M=$PWD modules

`-C` — перейти в сборку ядра и взять её правила, `M=` — где лежат твои файлы. Результат —
`имя.ko` (kernel object).

## Загрузка, журнал, выгрузка

| Команда | Что делает |
|---|---|
| `insmod файл.ko` | загрузить модуль из файла (зовётся init) |
| `lsmod` | что загружено |
| `dmesg \| tail` | последние сообщения ядра |
| `rmmod имя` | выгрузить (зовётся exit), имя без `.ko` |
| `modprobe имя` | загрузить системный модуль вместе с зависимостями |

При первой загрузке своего модуля ядро напишет `module verification failed` и
`taints kernel`. Это не ошибка: ядро помечает, что в нём побывал неподписанный код (флаг —
в `/proc/sys/kernel/tainted`, 0 — «чистое» ядро).

## Символьные устройства

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
