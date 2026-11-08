---
tags: ядро, модули, параметры, sys, module_param
---
# Параметры модулей

Модулю, как программе, передают аргументы — при загрузке, после имени файла:

    $ sudo insmod greet.ko name=Вася count=3
    $ sudo modprobe loop max_loop=16

Переменную объявляют параметром в коде модуля:

```c
static char *name = "гость";
module_param(name, charp, 0644);
MODULE_PARM_DESC(name, "Кого встречать");
```

Типы: `charp` (строка), `int`, `uint`, `long`, `bool`, `invbool`; массивы —
`module_param_array`. Описание видно в `modinfo`:

    $ modinfo greet.ko | grep parm
    parm:           name:Кого встречать (charp)

## /sys/module

Загруженный модуль виден в `/sys/module/<имя>/`, а его параметры — файлами в `parameters/`.
Третье число в `module_param` — права этого файла, как у `chmod`:

| Права | Что можно |
|---|---|
| `0` | файла нет вовсе |
| `0444` | читать всем, менять нельзя никому |
| `0644` | читать всем, менять root-у на ходу |

    $ cat /sys/module/greet/parameters/name
    Вася
    $ echo Петя | sudo tee /sys/module/greet/parameters/name

Модуль при этом не перезапускается: значение меняется в его памяти. Код, который уже отработал
(например, `init`), нового значения не увидит.

`/sys`, `/proc`, `/dev` показывает ядро, в котором ты работаешь. В задании модули живут в
учебном ядре — его `/sys` виден в шелле `kernel`.

## Источники

- [The Linux Kernel Module Programming Guide: Passing Command Line Arguments](https://sysprog21.github.io/lkmpg/#passing-command-line-arguments-to-a-module)
- [docs.kernel.org: sysfs](https://docs.kernel.org/filesystems/sysfs.html)
