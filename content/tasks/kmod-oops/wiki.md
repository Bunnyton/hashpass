---
tags: ядро, oops, panic, отладка, dmesg
---
# Когда падает ядро: oops и panic

Ошибка в программе убивает программу. Ошибка в модуле — это ошибка ядра. Ядро пишет в журнал
отчёт — **oops** — и пытается жить дальше; если не может — **panic**, система останавливается.

## Как читать oops

    BUG: kernel NULL pointer dereference, address: 0000000000000000
    #PF: supervisor read access in kernel mode
    Oops: 0000 [#1] PREEMPT SMP NOPTI
    CPU: 0 UID: 0 PID: 120 Comm: insmod Tainted: G           OE      6.12.116+deb13-amd64
    RIP: 0010:fill_box+0x5/0x20 [boxes]
    ...
    Call Trace:
     <TASK>
     boxes_init+0x61/0xff0 [boxes]
     do_one_initcall+0x58/0x300
     do_init_module+0x60/0x230

| Строка | Что значит |
|---|---|
| `BUG: …` | что случилось: NULL-указатель, обращение к чужой памяти |
| `address:` | куда полезли: 0 — сам NULL, чуть больше — поле структуры по NULL |
| `Comm: insmod` | какой процесс был в ядре — его ядро и убьёт (`Killed`) |
| `Tainted: … OE` | O — сторонний модуль, E — неподписанный |
| `RIP: функция+смещение/размер [модуль]` | где упало |
| `Call Trace` | кто звал: читать сверху вниз — от места падения к началу |

Номер строки по `функция+смещение` находит `scripts/faddr2line` из исходников ядра или
`gdb модуль.ko` → `list *(fill_box+0x5)`.

## После oops

Ядро «испорчено» (`/proc/sys/kernel/tainted` не 0), а модуль, упавший в `init`, застревает
полузагруженным: `rmmod` откажет, повторный `insmod` — `File exists`. Выход один —
перезагрузка. На серверах часто включают `panic_on_oops=1`: лучше перезагрузиться сразу, чем
работать с ядром, которое уже ошиблось.

## Источники

- [docs.kernel.org: Bug hunting](https://docs.kernel.org/admin-guide/bug-hunting.html)
- [docs.kernel.org: Tainted kernels](https://docs.kernel.org/admin-guide/tainted-kernels.html)
