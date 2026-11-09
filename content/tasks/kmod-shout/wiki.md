---
tags: ядро, C, драйверы, libc, параметры
---
# C в ядре: без libc

Модуль пишут на C, но стандартной библиотеки в ядре нет: `libc` — это код для программ, а ядро
работает под ними. Всё нужное ядро держит при себе, часто под теми же именами:

| в программе | в ядре |
|---|---|
| `<stdio.h>`: `printf` | `<linux/printk.h>`: `pr_info`, `pr_err` — пишут в журнал (`dmesg`) |
| `<string.h>`: `strlen`, `memcpy`, `strscpy` | `<linux/string.h>` — те же имена |
| `<ctype.h>`: `toupper`, `isdigit` | `<linux/ctype.h>` — те же имена, только для ASCII |
| `<stdlib.h>`: `malloc`, `free` | `<linux/slab.h>`: `kmalloc(размер, GFP_KERNEL)`, `kfree` |
| `atoi`, `strtol` | `<linux/kstrtox.h>`: `kstrtoint(строка, основание, &число)` |

Ещё отличия:

- **Нет плавающей точки.** `float` и `double` в ядре не используют — считают в целых.
- **Маленький стек** — несколько килобайт. Большие массивы — `static` или `kmalloc`.
- **Ошибка — это не исключение и не `exit`.** Функции возвращают `-EFAULT`, `-EINVAL`, `-ENOMEM`;
  ошибка в указателе роняет всё ядро (oops).
- **Текст — это байты.** `toupper` знает только латиницу: кириллица в UTF-8 занимает два байта, и
  ни один из них не «буква» для ядра.

## Источники

- [The Linux Kernel Module Programming Guide](https://sysprog21.github.io/lkmpg/)
- [Kernel API: строки и ctype](https://docs.kernel.org/core-api/kernel-api.html)
