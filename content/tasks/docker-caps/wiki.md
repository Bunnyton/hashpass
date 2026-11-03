---
tags: docker, capabilities, безопасность, права, ядро
---
# Привилегии ядра: root в контейнере — не всемогущий

Раньше в Linux было просто: root (uid 0) может всё, остальные — только своё. Потом «всё»
разрезали на десятки кусков — **привилегий ядра** (capabilities). Каждая разрешает одно:
менять владельца файлов, переводить часы, слать сигналы чужим процессам. Ядро проверяет не
«ты root?», а «есть ли у тебя вот эта привилегия?».

## Root в контейнере

Процесс в контейнере по умолчанию — root:

    $ docker run --rm alpine sh -c 'whoami; id'
    root
    uid=0(root) gid=0(root) groups=0(root),…

Но docker даёт ему не все привилегии, а урезанный набор. Часы, например, root в контейнере
перевести не может:

    $ docker run --rm alpine date -s 2000-01-01
    date: can't set date: Operation not permitted

## Как посмотреть набор

Набор процесса — в `/proc/<pid>/status`, строки `Cap…`, битовой маской:

    $ docker run --rm alpine grep Cap /proc/self/status
    CapInh:	0000000000000000
    CapPrm:	00000000a80425fb
    CapEff:	00000000a80425fb
    CapBnd:	00000000a80425fb
    CapAmb:	0000000000000000

`CapEff` — то, что действует сейчас. Расшифровывает маску `capsh` (пакет `libcap2-bin` в
Debian, `libcap-utils` в Alpine):

    $ capsh --decode=00000000a80425fb
    0x00000000a80425fb=cap_chown,cap_dac_override,cap_fowner,cap_fsetid,cap_kill,cap_setgid,cap_setuid,cap_setpcap,cap_net_bind_service,cap_net_raw,cap_sys_chroot,cap_mknod,cap_audit_write,cap_setfcap

Это и есть набор docker по умолчанию — 14 из примерно сорока. Нет в нём, например,
`SYS_TIME` (часы), `SYS_ADMIN` (монтирование и «почти всё»), `NET_ADMIN` (настройка сети),
`SYS_MODULE` (модули ядра). Что разрешает каждая — `man 7 capabilities`.

## Менять набор: `--cap-drop` и `--cap-add`

    --cap-drop ALL            сбросить все
    --cap-add  NET_ADMIN      добавить одну (имя — без приставки CAP_)

Без единой привилегии маска — нули:

    $ docker run --rm --cap-drop ALL alpine grep CapEff /proc/self/status
    CapEff:	0000000000000000

И root становится просто пользователем с номером 0. Пример: обычный root читает любой файл,
даже с правами `000`, — это привилегия `DAC_OVERRIDE` («обходить права доступа»). Сбросил
всё — не читает:

    $ docker run --rm --cap-drop ALL alpine sh -c 'echo секрет > /tmp/f; chmod 000 /tmp/f; cat /tmp/f'
    cat: can't open '/tmp/f': Permission denied

Вернул ровно одну — снова читает:

    $ docker run --rm --cap-drop ALL --cap-add DAC_OVERRIDE alpine sh -c 'echo секрет > /tmp/f; chmod 000 /tmp/f; cat /tmp/f'
    секрет

Ещё одна, `MKNOD` — создавать файлы устройств:

    $ docker run --rm --cap-drop ALL alpine mknod /tmp/null c 1 3
    mknod: /tmp/null: Operation not permitted

## Правило безопасности

1. Сбрось всё (`--cap-drop ALL`).
2. Добавь только то, без чего сервис не работает.
3. Что ему нужно, узнают опытом: запусти без всего и прочитай `docker logs` — на чём упал.
   Ошибки вида `Operation not permitted` или `Permission denied` у root — почти всегда
   недостающая привилегия. Найди в `man 7 capabilities` ту, что описывает эту операцию.

Смысл простой: взломают сервис — у взломщика окажется root, который умеет ровно одно дело.
Контейнер с неправильным набором проще удалить и запустить заново: `docker rm -f <имя>`.

## Противоположность: `--privileged`

`--privileged` даёт контейнеру **все** привилегии разом, доступ к устройствам машины и снимает
остальные ограничения — по сути, root на хосте. Его ставят только когда без него никак
(например, docker внутри docker) и всегда с вопросом «зачем?». Если нужна одна возможность —
добавь одну привилегию, а не все.

## Где пригодится

- проверка безопасности контейнеров: `docker inspect -f '{{.HostConfig.CapAdd}} {{.HostConfig.CapDrop}}' <имя>`;
- в compose — те же поля `cap_drop:` и `cap_add:` у сервиса;
- вне docker: `getcap`/`setcap` выдают привилегию одной программе вместо setuid-root.

## Источники

- `man 7 capabilities` — [на man7.org](https://man7.org/linux/man-pages/man7/capabilities.7.html):
  полный список и что разрешает каждая.
- [Runtime privilege and Linux capabilities](https://docs.docker.com/engine/containers/run/) —
  документация Docker: набор по умолчанию, `--cap-add`, `--privileged`.
- [Docker security](https://docs.docker.com/engine/security/) — как docker изолирует
  контейнеры: пространства имён, cgroups, capabilities.
- [Capabilities — ArchWiki](https://wiki.archlinux.org/title/Capabilities) — примеры с
  `getcap`/`setcap`.
