---
tags: ядро, модули, modprobe, depmod, автозагрузка
---
# modprobe, depmod и автозагрузка

`insmod` берёт файл по пути. Системные модули грузит `modprobe` — по **имени**, вместе с
зависимостями:

    $ sudo modprobe loop
    $ sudo modprobe -r loop          # выгрузить
    $ modprobe -c | grep loop        # что modprobe знает о модуле

## Где лежат модули

    /lib/modules/<версия ядра>/
    ├── kernel/        модули самого ядра
    ├── updates/       сторонние (сюда ставит make modules_install)
    ├── extra/         сторонние (так принято у DKMS и др.)
    └── modules.dep    кто где лежит и от кого зависит

`modprobe` не ищет по диску — он читает `modules.dep`. Его обновляет `depmod` (`depmod -a`).
Свой модуль ставят так:

    $ sudo make -C /lib/modules/$(uname -r)/build M=$PWD modules_install
    $ sudo modprobe hello

или руками: `cp hello.ko /lib/modules/$(uname -r)/extra/ && sudo depmod -a`.

## Автозагрузка

При старте `systemd-modules-load` читает `/etc/modules-load.d/*.conf` (и старый
`/etc/modules`) — имя модуля на строку:

    # /etc/modules-load.d/hello.conf
    hello

Параметры по умолчанию и запреты — `/etc/modprobe.d/*.conf`:

    options hello who=Сервер
    blacklist pcspkr

Большую часть драйверов ядро грузит и без списков: устройство сообщает свой `alias`
(`modinfo` показывает их), `udev` находит подходящий модуль и зовёт `modprobe`.

## Источники

- [modprobe(8)](https://man7.org/linux/man-pages/man8/modprobe.8.html), [depmod(8)](https://man7.org/linux/man-pages/man8/depmod.8.html)
- [modules-load.d(5)](https://man7.org/linux/man-pages/man5/modules-load.d.5.html), [modprobe.d(5)](https://man7.org/linux/man-pages/man5/modprobe.d.5.html)
- [docs.kernel.org: Building External Modules](https://docs.kernel.org/kbuild/modules.html)
