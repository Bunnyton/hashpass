---
tags: git, pull request, конфликт, CI, тесты, merge, rebase
---
# Pull request не сливается

Под кнопкой слияния хостинг пишет, что мешает. Два частых случая.

## Конфликт с main

Пока PR ждал, в main влили другой PR, и он правит те же строки. Хостинг конфликты не
разбирает. Разбирают у себя:

    $ git fetch
    $ git merge origin/main
    Auto-merging CHANGELOG.md
    CONFLICT (content): Merge conflict in CHANGELOG.md
    $ vim CHANGELOG.md             # оставить обе строки, убрать <<<<<<< ======= >>>>>>>
    $ git add CHANGELOG.md
    $ git commit --no-edit
    $ git push

Или перестройка: `git rebase origin/main`, разбор, `git rebase --continue` и
`git push --force-with-lease` — в своей ветке PR так тоже можно.

## Проверки красные

git сложил правки без конфликта — но это ещё не значит, что программа работает. В примере
Олег поменял формат чека («К оплате» → «Итого»), а `combo.sh` из ветки PR разбирал старый:

    $ ./test.sh
    ok   пельмени-говядина x2
    ok   морс x3
    ./combo.sh: 6: Illegal number: Итого: 350 ₽
    FAIL комбо: «./combo.sh: 6: Illegal number: Итого: 350 ₽», ждали «Комбо: 423 ₽»

Такой **семантический конфликт** видят только тесты. Поэтому хостинги гоняют проверки
(CI — GitHub Actions, GitLab CI) на каждом PR и после каждого push в его ветку.

## Чтобы реже попадать

- Маленькие PR, которые сливают быстро.
- Подтягивать main в ветку, пока PR ждёт ревью.
- Защита ветки «Require branches to be up to date» на GitHub: слить можно, только если ветка
  включает свежий main и проверки на этом коде прошли.

## Источники

- [GitHub Docs: Resolving a merge conflict on GitHub](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/addressing-merge-conflicts/resolving-a-merge-conflict-using-the-command-line) —
  разбор конфликта PR в командной строке.
- [GitHub Docs: About status checks](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/about-status-checks) —
  проверки на PR.
- [Pro Git: Основы конфликтов слияния](https://git-scm.com/book/ru/v2/Ветвление-в-Git-Основы-ветвления-и-слияния) —
  раздел «Основные конфликты слияния».
