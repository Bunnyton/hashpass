# git-pr-review: студент — ревьюер PR Олега «Скидка постоянным». Ошибка: скидка вычитается
# второй раз в строке echo (всем клиентам), а ожидания в test.sh подогнаны под неё.
# Комментарий к одной из этих строк + «запросить изменения» → Олег чинит (два коммита).
# Одобрить до исправления — Анна просит подождать. Слить можно только squash.
BUG = {("order.sh", 9), ("test.sh", 5), ("test.sh", 6)}
FIX = "/usr/local/lib/lepka/fix"   # order.sh и test.sh после исправления


def _found(pr):
    return any(e["kind"] == "comment" and e["author"] == "student" and
               (e.get("path"), e.get("line")) in BUG for e in pr["timeline"])


def _fix(pr, api):
    for path, msg in (("order.sh", "Скидка: один раз и только постоянным"),
                      ("test.sh", "Тесты: обычный клиент платит полную цену, постоянный — минус 5 %")):
        with open(f"{FIX}/{path}", encoding="utf-8") as f:
            api.commit_file(pr["head"], "Олег Кузнецов", "oleg@pelmen.local", msg, path, f.read())
    api.pushed(pr, "oleg")
    pr["fixed"] = True
    api.say(pr, "oleg", "Ты прав, скидка вычиталась второй раз — у всех. А тесты я подогнал "
                        "под ошибку, стыдно. Поправил и то и другое, посмотри ещё раз.")


def on_event(event, pr, api, **kw):
    fixed = pr.get("fixed")
    if event == "opened":
        api.say(pr, "anna", "Студент, посмотри, пожалуйста, — я сегодня на выезде. "
                            "Касса — дело денежное, читай внимательно.")
    elif event == "comment" and kw.get("path"):
        if fixed:
            return
        if (kw["path"], kw["line"]) in BUG:
            api.say(pr, "oleg", "Хм, сейчас гляну. Допиши ревью целиком — что нужно исправить.",
                    kw["path"], kw["line"])
        else:
            api.say(pr, "oleg", "Тут вроде всё как задумано. Точно эта строка?",
                    kw["path"], kw["line"])
    elif event == "review" and kw.get("state") == "changes" and not fixed:
        if _found(pr):
            _fix(pr, api)
        else:
            api.say(pr, "oleg", "А что именно не так? Покажи строку — значок 💬 у неё в изменениях.")
    elif event == "review" and kw.get("state") == "approved":
        if not fixed:
            api.review(pr, "anna", "changes",
                       "Погоди одобрять. Посчитай, сколько заплатит обычный клиент за две порции "
                       "говядины, — и сравни с тем, что ждут тесты.")
        elif pr["reviews"].get("anna", {}).get("state") == "changes":
            api.review(pr, "anna", "approved", "Теперь верно. Спасибо за внимательное ревью.")


def check_method(pr, method):
    if method != "squash":
        return "Правило команды: в main — один коммит на pull request. Выбери squash."
    return None
