[![Watch the video](/docs/photo/hashpass.png)](https://rutube.ru/video/private/37627480156ee69286cb988bc4b2ac25/?p=b9p6xcUlqOUY8EyyyyH-4w)

# hashpass

hashpass — инструмент для интерактивных заданий и лабораторных по Linux. Автор описывает задание в одном текстовом файле на DSL, из него собирается образ-контейнер, а студент решает задание в живой консоли настоящей системы Debian: `systemd-nspawn` запускает контейнер, а `overlayfs` даёт отдельный рабочий слой.

## Как работает

Студент вводит обычные Linux-команды в контейнере. После каждой команды hashpass невидимо проверяет текущее состояние с хоста, вне контейнера: сравнивает файловую систему и/или вывод с эталоном, который получен из авторского решения. Студент не видит проверяющие команды, грейдеры, скрытые файлы и ключи.

Если в рецепте есть блок `stage`, `hashpass run` запускает интерактивное задание. Если блоков `stage` нет, запускается обычная контейнер-среда с shell.

## Требования

- Python 3.13.
- `systemd-nspawn` из пакета `systemd-container`.
- `overlayfs`.
- Docker — только для одноразового экспорта базового rootfs из `debian:trixie-slim`.
- Scoped passwordless sudo на конкретные команды: `mount`, `umount`, `systemd-nspawn`, `rsync`, `tar`, `machinectl`.

## Установка

```bash
make install
```

Команда устанавливает CLI `hashpass` в `PATH` как editable-пакет через `pip install --user -e .`.

Удаление:

```bash
make uninstall
```

Без установки CLI можно запускать как модуль:

```bash
python3 -m hashpass <команда>
```

Данные и кэш хранятся в `~/.hashpass`. Путь можно переопределить переменной окружения `HASHPASS_HOME`.

## Быстрый старт

```bash
make install                                   # поставить hashpass
cd content/tasks/showcase                       # эталонное задание в репозитории
hashpass build Taskfile                         # спросит логин один раз; напечатает ref <логин>/showcase:1
hashpass run <логин>/showcase:1                 # пройти задание в консоли (exit — выйти)
```

`hashpass build` сохраняет образ в namespace владельца, поэтому запускать нужно по ref, который CLI напечатал в строке `собрано` — например `alice/showcase:1`.

`showcase` — эталонное задание из репозитория. Оно демонстрирует наблюдение за файлами, проверку по выводу, `variant`, `allow`/`deny`, inline `check exec`, `accept cmd`, скрытый грейдер и финал.

## Дальше

Подробная инструкция по установке, командам CLI и прохождению заданий: [docs/Инструкция пользователя (user guide).md](<docs/Инструкция пользователя (user guide).md>).

Полный справочник DSL для авторов заданий: [docs/Авторинг заданий (task authoring).md](<docs/Авторинг заданий (task authoring).md>).
