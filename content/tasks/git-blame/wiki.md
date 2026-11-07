---
tags: git, blame, log, история, расследование
---
# git blame: кто поменял строку

`git blame` подписывает каждую строку файла коммитом, который менял её последним:

    $ git blame config.ini
    ef3769a3 (Анна Смирнова 2026-09-04 02:00:00 +0000 1) [server]
    293dce54 (Вася Пупкин   2026-10-11 02:00:00 +0000 2) host = 0.0.0.0
    99bd0947 (Олег Кузнецов 2026-10-17 06:00:00 +0000 3) port = 8081
    293dce54 (Вася Пупкин   2026-10-11 02:00:00 +0000 4) timeout = 1

## Ловушка: форматирование

`293dce54` — «Форматирование конфига: пробелы вокруг =». Вася поменял все строки, но смысл ни
одной. Как заглянуть за такой коммит:

    $ git blame -w config.ini | grep timeout
    e33ddc08 (Пётр Иванов   2026-09-30 07:00:00 +0000 4) timeout = 1

| Команда | Что делает |
|---|---|
| `git blame -w файл` | не замечать правки только в пробелах |
| `git blame <хеш>^ -- файл` | blame на момент до коммита `<хеш>` |
| `git blame -L 4,4 файл` | только строки 4–4 |
| `git log -L 4,4:файл` | вся история этих строк, с правками |
| `git blame -C файл` | найти строки, перенесённые из других файлов |

Чтобы blame всегда пропускал коммиты форматирования, их перечисляют в файле
`.git-blame-ignore-revs` и включают `git config blame.ignoreRevsFile .git-blame-ignore-revs`.
GitHub понимает этот файл сам.

## Нашёл — что дальше

Смотри сообщение: `git show e33ddc08` — «Тесты: не ждать ответа по 30 секунд». Теперь понятна
и причина, и как чинить, не сломав то, ради чего правили. Возвращая значение, сошлись на
коммит в сообщении — следующий, кто запустит blame, поймёт всё сразу.

## Источники

- [git blame](https://git-scm.com/docs/git-blame) — официальная документация: `-w`, `-L`, `-C`,
  `--ignore-revs-file`.
- [Pro Git: Отладка с помощью Git](https://git-scm.com/book/ru/v2/Инструменты-Git-Обнаружение-ошибок-с-помощью-Git) —
  blame и bisect.
- [GitHub Docs: Viewing a file's blame](https://docs.github.com/en/repositories/working-with-files/using-files/viewing-and-understanding-files#ignore-commits-in-the-blame-view) —
  `.git-blame-ignore-revs`.
