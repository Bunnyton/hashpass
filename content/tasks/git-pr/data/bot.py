# git-pr: Анна — ревьюер кассы. Просит строку в CHANGELOG.md, пока её нет; есть — одобряет.
def _changelog_ok(pr, api):
    mb = api.git("merge-base", "main", pr["head_sha"]).stdout.strip()
    diff = api.git("diff", mb, pr["head_sha"], "--", "CHANGELOG.md").stdout.lower()
    return any(l.startswith("+") and "вареник" in l for l in diff.split("\n"))


def on_event(event, pr, api, **kw):
    if event not in ("opened", "updated"):
        return
    if _changelog_ok(pr, api):
        api.review(pr, "anna", "approved",
                   "Теперь всё на месте: вареники в меню и в CHANGELOG. Одобряю — можно сливать.")
    elif event == "opened":
        api.say(pr, "anna", "Спасибо за PR! Касса считает, тесты зелёные.")
        api.review(pr, "anna", "changes",
                   "Одно но: у нас каждое изменение записывают в CHANGELOG.md. Допиши туда "
                   "строку про вареники — прямо в этой же ветке, PR обновится сам.")
    else:
        api.say(pr, "anna", "Вижу новые коммиты, но в CHANGELOG.md про вареники пока ничего нет.")
