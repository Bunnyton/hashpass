---
tags: git, pull request, merge request, ревью, код-ревью, CI
---
# Pull request

Pull request (на GitLab — merge request) — просьба влить ветку в main, оформленная на сайте
хостинга: GitHub, GitLab, Gitea, Bitbucket. Устроены они одинаково.

## Цикл

    git switch -c vareniki
    # правки, коммиты
    git push -u origin vareniki

На сайте: «New pull request» / «открыть pull request» → ветка → заголовок и описание.

На странице PR:

- **изменения** (diff) — что сольётся в main;
- **проверки** (CI) — сервер сам запускает тесты на коде ветки;
- **ревью** — коллеги одобряют или просят изменений, комментируют конкретные строки;
- **кнопка слияния** — доступна, когда ничего не мешает: нет конфликта, тесты зелёные,
  есть одобрение.

## Ревьюер просит доработать

Новый PR не нужен. Коммить в ту же ветку и отправь — PR обновится сам, проверки пройдут
заново:

    git commit -am "CHANGELOG: вареники"
    git push

## После слияния

    git switch main
    git pull                 # main с сервера — уже с твоей веткой
    git branch -d vareniki   # -d удалит, только если ветка влита

## Способы слияния

| Кнопка | Что в main |
|---|---|
| Merge commit | коммиты ветки + коммит слияния |
| Squash and merge | один новый коммит со всеми правками |
| Rebase and merge | коммиты ветки по одному, без коммита слияния |

Что выбрать — правило команды.

## Хороший pull request

- Одна задача — один PR. Маленький PR смотрят за минуты, огромный — неделю.
- Заголовок — что делает PR, описание — зачем и как проверить.
- Перед отправкой — свои тесты и `git diff main...` глазами.

## Источники

- [GitHub Docs: About pull requests](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests) —
  что такое PR и как с ним работают.
- [GitLab Docs: Merge requests](https://docs.gitlab.com/user/project/merge_requests/) —
  то же в GitLab.
- [Pro Git: GitHub — внесение собственного вклада](https://git-scm.com/book/ru/v2/GitHub-Внесение-собственного-вклада-в-проекты) —
  цикл ветка → PR → ревью → слияние.
