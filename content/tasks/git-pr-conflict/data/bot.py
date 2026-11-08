# git-pr-conflict: Анна одобряет оба PR при открытии; на обновления отвечает по проверкам.
def on_event(event, pr, api, **kw):
    if event == "opened":
        api.review(pr, "anna", "approved", "Посмотрела — всё понятно. Одобряю.")
    elif event == "updated" and pr["author"] == "student":
        ci = pr["checks"].get(pr["head_sha"], {})
        if ci.get("status") == "fail":
            api.say(pr, "anna", "Конфликта больше нет, но проверки красные — глянь вывод ./test.sh.")
        elif ci.get("status") == "ok":
            api.say(pr, "anna", "Зелёное. Сливай, когда будешь готов.")
