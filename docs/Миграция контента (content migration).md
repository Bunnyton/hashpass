# Миграция контента (content migration)

## 1. Почему это не авто-миграция
Старые 24 задания (`origin/dev`) хранят ТОЛЬКО одностороннюю Simhash-сигнатуру
ожидаемого состояния ФС (`changes: path -> {hash, state, is_dir}`) + hint-`actions`.
Эталонных команд и восстановимых байтов в них НЕТ. Новый конвейер (План D)
деривирует приём, ЗАПУСКАЯ эталонные команды, поэтому старые задания
авто-сконвертировать нельзя — нечего запускать, а Simhash необратим.
Вывод: авторируем задания заново как task-as-код + пишем этот плейбук.

## 2. Паттерн авторинга
1. Пишем `content/tasks/<id>/task.toml`: `id`, `setup=[...]`, один или несколько
   `[[stage]]` с `commands` (эталонное решение), `observe` (наблюдаемые пути),
   опц. `exclude`, `message`.
2. Деривируем бандл: `derive_checks(factory, task, passes=3)` → `Bundle(...)` →
   `dump_bundle`. `factory` отдаёт СВЕЖИЙ подготовленный `TmpdirRunner` на каждый
   проход. `derive_checks` бросает `ValueError`, если канон вакуумный
   (нет стабильного сигнала).
3. Валидируем харнессом Задачи 2 (`tests/content/test_pipeline.py`): верное
   решение → `feed(...).advanced` и `local_key` начинается с `key{`; неверное →
   не `advanced`, `local_key is None`.

## 3. Детерминизм наблюдаемого набора (обязательно)
Наблюдаемые файлы должны быть СТАБИЛЬНЫ на k проходах: перенаправляем вывод в
файл; в наблюдаемом наборе НЕТ времени/PID/случайности. Волатильные поля канон
сам обрежет (дифф-канонизация, §5) — но если стабильного сигнала не осталось,
`derive_checks` упадёт с `vacuous canonical`. Пример волатильного, которое надо
исключать: `date +%s%N`.

## 4. Три задания-примера (worked examples)
- `hello` — output/fs: `echo hello > hello.txt`, observe `hello.txt`;
  канон `{'hello.txt': ('file','hello\n'), '<output>': ('file','')}`.
- `list-files` — `ls` детерминирован (сортировка): `ls work > listing.txt`,
  observe `listing.txt`; канон `listing.txt = "a\nb\nc\n"`.
- `grep-todo` — seed через `printf` (в TOML basic-строке `\n` = реальный
  перевод строки), `grep TODO notes.txt > found.txt`, observe `found.txt`;
  канон `found.txt = "TODO fix\n"`.

## 5. Контейнерные/сетевые задания (apt, sudo, …)
Такие задания НЕЛЬЗЯ деривировать в `TmpdirRunner` (нет пакетов/сети/root).
Авторим и деривируем их В КОНТЕЙНЕРЕ — tier2 (rootless overlay) или tier3
(`NspawnRunner` + `base_tar`), как в `tests/content/test_e2e_nspawn.py`.
Деривацию можно делать host-side на `TmpdirRunner`, только если наблюдаемый
эффект не зависит от контейнерного окружения; иначе — контейнерный фактори.

## 6. Остаток
Оставшиеся ~20 из 24 dev-заданий — content-ops follow-on по этому плейбуку
(в первую очередь контейнерные/сетевые). Каждое: task.toml → derive → валидация
харнессом Задачи 2 (+ tier3 для контейнерных).
