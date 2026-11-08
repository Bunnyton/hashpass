---
tags: ядро, модули, insmod, dmesg, kbuild
---
# Модули ядра

**Ядро** — программа, которая управляет железом, памятью и процессами. **Модуль** — кусок
кода, который подгружается в уже работающее ядро без перезагрузки. Так приходят почти все
драйверы: сетевые карты, файловые системы, USB. Здесь — как модули устроены и как их собирают.

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

Правило одно: модуль собирают под **то ядро, где он будет жить**. Опыты со своими модулями
ставят в виртуальной машине: ошибка в модуле роняет не программу, а всё ядро целиком.

В задании так и устроено: консоль работает на **учебном ядре** — маленькой ВМ, которой отдана
файловая система консоли. `insmod`, `rmmod`, `lsmod`, `modprobe`, `depmod`, `dmesg` и
`uname -r` в консоли говорят с ним, а `kernel` открывает шелл внутри (там его `/dev`, `/proc`,
`/sys`). Упадёт — `sudo systemctl restart hpkernel`.

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
