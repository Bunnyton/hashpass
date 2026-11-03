---
tags: git, gitignore, файлы, секреты
---
# .gitignore: что git не должен видеть

В рабочем каталоге всегда лежит то, чему в истории не место: журналы, результаты сборки
(их соберут заново из исходников), кэш, временные файлы редактора, пароли. Не спрячешь —
`git status` станет простынёй, а `git add .` однажды утащит всё это в коммит.

## Проблема

Блог, в котором работали пару дней:

    $ git status -s
    ?? .about.html.swp
    ?? about.html
    ?? debug.log
    ?? public/
    ?? server.log
    ?? tmp/

Нужный новый файл тут один — `about.html`. Остальное — мусор: журналы, сборка, временный
каталог и файл подкачки vim (`.имя.swp` появляется, пока файл открыт в редакторе).

## Файл .gitignore

В корне проекта заводят файл `.gitignore` — по шаблону на строку:

    $ cat .gitignore
    # журналы
    *.log
    # сборка
    public/
    tmp/
    *.swp
    $ git status -s
    ?? .gitignore
    ?? about.html

Сам `.gitignore` коммитят как обычный файл: правила нужны всей команде. А шаблоны работают и
на будущее — завтрашний `2027.log` git уже не заметит.

## Как пишутся шаблоны

| Шаблон | Что прячет |
|---|---|
| `*.log` | любой файл с окончанием `.log` — в любом каталоге проекта |
| `build/` | каталог `build` целиком, где бы он ни был; `/` в конце — «только каталог» |
| `/todo.txt` | `/` в начале — только в корне проекта, не в подкаталогах |
| `docs/*.pdf` | pdf прямо в `docs`, но не в `docs/old/` |
| `**/cache` | `cache` на любой глубине |
| `.*` | все скрытые файлы — осторожно, спрячет и нужные |
| `!keep.log` | `!` — исключение: этот файл всё-таки показывать |
| `# текст` | комментарий |

`*` — любые символы, кроме `/`; `?` — один символ; `[abc]` — один из набора. Это не
регулярки, а те же шаблоны, что в шелле (`ls *.txt`).

## Проверить, что спрятано и почему

    $ git status --ignored -s
    ?? .gitignore
    ?? about.html
    !! .about.html.swp
    !! debug.log
    !! public/
    !! server.log
    !! tmp/

`!!` — проигнорировано. Какое правило сработало — `git check-ignore -v`:

    $ git check-ignore -v debug.log public/img/logo.png
    .gitignore:2:*.log	debug.log
    .gitignore:4:public/	public/img/logo.png

Добавить игнорируемый файл git откажется, пока не настоишь ключом `-f`:

    $ git add notes.tmp
    The following paths are ignored by one of your .gitignore files:
    notes.tmp
    hint: Use -f if you really want to add them.
    hint: Disable this message with "git config advice.addIgnoredFile false"

## Ловушка: то, что уже в истории

`.gitignore` касается только **неотслеживаемых** файлов — тех, которых в репозитории ещё нет.
Файл, который однажды закоммитили, git знает и продолжает за ним следить, что бы ни было
написано в `.gitignore`:

    $ echo 'config.local' >> .gitignore
    $ git status -s
     M config.local
    ?? .gitignore

Правило есть, а `config.local` всё равно в списке изменённых. Чтобы git его отпустил, файл
убирают **из индекса** (из списка файлов репозитория), не трогая на диске, и делают коммит
«файла больше нет». Обычный `git rm` сотрёт файл и с диска — у него есть ключ, который трогает
только индекс; найди его в `git rm --help`. Что сейчас в репозитории — покажет `git ls-files`.

## Секрет в истории — уже утёк

Даже убранный из репозитория файл остаётся в старых коммитах:

    $ git log -p --oneline -- config.local
    dae19d4 Локальные настройки
    diff --git a/config.local b/config.local
    new file mode 100644
    index 0000000..84cbeab
    --- /dev/null
    +++ b/config.local
    @@ -0,0 +1 @@
    +DB_PASSWORD=qwerty

Если репозиторий уходил на сервер, такой пароль считают утёкшим и **меняют**. Вычистить его
из истории можно (`git filter-repo`), но это переписывает все коммиты у всей команды. Поэтому
секреты держат вне git с самого начала: `.env` в `.gitignore`, а в репозитории — пример
`.env.example` без настоящих значений.

## Свои правила только для себя

- `.git/info/exclude` — как `.gitignore`, но не коммитится: правила одного репозитория у тебя.
- `core.excludesFile` в `~/.gitconfig` — глобальный список для всех репозиториев (файлы твоего
  редактора, `.DS_Store` на маке).

## Источники

- [gitignore](https://git-scm.com/docs/gitignore) — официальная документация, раздел
  PATTERN FORMAT с примерами.
- [man gitignore на man7.org](https://man7.org/linux/man-pages/man5/gitignore.5.html).
- [Pro Git: Запись изменений в репозиторий](https://git-scm.com/book/ru/v2/Основы-Git-Запись-изменений-в-репозиторий) —
  раздел «Игнорирование файлов».
- [github/gitignore](https://github.com/github/gitignore) — готовые `.gitignore` для языков и
  фреймворков.
- [git check-ignore](https://git-scm.com/docs/git-check-ignore) — почему файл спрятан.
