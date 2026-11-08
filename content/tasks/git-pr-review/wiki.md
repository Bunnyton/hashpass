---
tags: git, pull request, ревью, код-ревью, squash, тесты
---
# Ревью pull request

Ревью — чтение чужих изменений перед слиянием. Цель — не стиль, а то, что автор мог
пропустить: ошибки, забытые случаи, лишнее, тесты, которые ничего не проверяют.

## Что смотреть

1. **Описание** — что PR обещает сделать.
2. **Изменения** (diff) — каждая строка с `+` и `-`. Что она делает? Что будет на обычных
   данных и на краевых?
3. **Тесты** — если тест поменяли вместе с кодом, проверь, что он не подогнан под новое
   поведение. Зелёные проверки ничего не доказывают, если ожидания переписали.
4. Сомневаешься — забери ветку и запусти:

       git fetch
       git switch regulars
       ./test.sh
       ./order.sh пельмени-говядина 2

## Как писать замечания

- К **строке**, а не «где-то в PR»: значок у строки в изменениях.
- Что не так и почему, с примером: «обычный клиент за 2 × 350 заплатит 665 вместо 700».
- Решение — отзыв целиком: **запросить изменения**, **одобрить** или **комментарий**.

## Слить одним коммитом: squash

    $ git log --oneline main
    a41c2e9 Скидка 5 % постоянным клиентам (#1)
    9916873 Касса: меню, сумма заказа, проверки

Все коммиты PR, включая «поправил по ревью», превращаются в один. История main читается
как список фич, а подробности остаются на странице PR.

## Источники

- [Google Engineering Practices: What to look for in a code review](https://google.github.io/eng-practices/review/reviewer/looking-for.html) —
  на что смотреть ревьюеру.
- [GitHub Docs: Reviewing proposed changes in a pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/reviewing-proposed-changes-in-a-pull-request) —
  комментарии к строкам и итог ревью.
- [GitHub Docs: About merge methods](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/about-merge-methods-on-github) —
  merge, squash и rebase.
