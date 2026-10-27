"""
`hashpass course …` -- a course from the console (user 2026-10-27: «унификация»).

Pushing an image and putting it into a course are separate operations, and both go to the pool's
one course API -- the same `/courses/…` requests the course page in the browser makes. Nothing
here decides anything the server does not: the console only names things and says the answer.

    hashpass course                                   courses I see
    hashpass course new <name> [--title T] [--private]
    hashpass course <course>                          its blocks and tasks
    hashpass course <course> add block <name>
    hashpass course <course> block <name> add <ref>…  (a task already elsewhere moves here)
    hashpass course <course> block <name> rm <ref>…
    hashpass course <course> block <name> rename <new name>
    hashpass course <course> rm block <name>
    hashpass course <course> set title|description|visibility <value>
    hashpass course <course> set name <new name>     a new address; the old one is gone

<course> is owner/name, a name of one's own, or a title; a block is its name or id.
"""
import contextlib
import json
import urllib.error
import urllib.parse
from collections.abc import Callable
from typing import TextIO

from hashpass.registry.remote import RemoteRegistry

USAGE = (
    "hashpass course                                    — курсы, которые я вижу\n"
    "hashpass course new <имя> [--title T] [--private]  — новый курс\n"
    "hashpass course <курс>                             — блоки и задания курса\n"
    "hashpass course <курс> add block <имя>             — новый блок\n"
    "hashpass course <курс> block <блок> add <ref>…     — задания в блок\n"
    "hashpass course <курс> block <блок> rm <ref>…      — убрать задания из курса\n"
    "hashpass course <курс> block <блок> rename <имя>   — переименовать блок\n"
    "hashpass course <курс> rm block <блок>             — удалить блок\n"
    "hashpass course <курс> set title|description|visibility <значение>\n"
    "hashpass course <курс> set name <имя>              — новый адрес курса (старый перестаёт работать)\n"
)
_SETTINGS = ("title", "description", "visibility", "name")


class CourseApi:
    """JSON requests to the pool's course API as one person (a token), errors in plain Russian."""

    def __init__(self, client: RemoteRegistry, token: str) -> None:
        """`client` knows the pool's address; `token` -- whose rights the requests carry."""
        self.client = client
        self.token = token

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.token}"}
        data = None
        if body is not None or method in ("POST", "PUT"):
            headers["Content-Type"] = "application/json"
            data = json.dumps(body or {}).encode("utf-8")
        try:
            raw = self.client._send(method, path, data=data, headers=headers)  # noqa: SLF001
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            with contextlib.suppress(ValueError, AttributeError):
                text = str(json.loads(text).get("error", text))
            raise RuntimeError(text or f"пул ответил {exc.code}") from exc
        return json.loads(raw.decode("utf-8")) if raw else {}


def run_course(api: CourseApi, user: str, words: list[str], *, out: TextIO) -> int:
    """Do one `hashpass course …` command; RuntimeError carries what went wrong."""
    words, opts = _options(words)
    if not words:
        return _list(api, out)
    if words[0] == "new":
        return _create(api, words[1:], opts, out)
    ref = _course_ref(api, user, words[0])
    rest = words[1:]
    if not rest:
        return _show(api, ref, out)
    action = _ACTIONS.get(tuple(rest[:2])) or _ACTIONS.get((rest[0], rest[2] if len(rest) > 2 else ""))  # noqa: PLR2004
    if action is None:
        msg = "не понял команду.\n" + USAGE
        raise RuntimeError(msg)
    return action(api, user, ref, rest, out)


def _options(words: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split `--title T` / `--private` off the words."""
    rest: list[str] = []
    opts: dict[str, str] = {}
    i = 0
    while i < len(words):
        w = words[i]
        if w == "--title" and i + 1 < len(words):
            opts["title"] = words[i + 1]
            i += 2
            continue
        if w in ("--private", "--public"):
            opts["visibility"] = w[2:]
        else:
            rest.append(w)
        i += 1
    return rest, opts


def _path(ref: str) -> str:
    return "/courses/" + "/".join(urllib.parse.quote(p, safe="") for p in ref.split("/", 1))


def _course_ref(api: CourseApi, user: str, name: str) -> str:
    """owner/name as is; else a course named so in one's own namespace, else by its title."""
    if "/" in name:
        return name
    rows = api.call("GET", "/courses").get("courses", [])
    own = [r["ref"] for r in rows if r["ref"] == f"{user}/{name}"]
    named = own or [r["ref"] for r in rows if r["ref"].split("/", 1)[1] == name]
    titled = named or [r["ref"] for r in rows if str(r.get("title", "")).casefold() == name.casefold()]
    if len(titled) == 1:
        return titled[0]
    if not titled:
        msg = f"нет курса «{name}». Курсы: hashpass course"
        raise RuntimeError(msg)
    msg = f"«{name}» — несколько курсов: {', '.join(titled)}. Назовите владелец/имя"
    raise RuntimeError(msg)


def _view(api: CourseApi, ref: str) -> dict:
    return api.call("GET", _path(ref))


def _block(view: dict, name: str) -> dict:
    for b in view.get("blocks", []):
        if b["id"] == name or str(b["name"]).casefold() == name.casefold():
            return b
    msg = f"в курсе {view.get('ref', '')} нет блока «{name}»"
    raise RuntimeError(msg)


def _task_ref(user: str, ref: str) -> tuple[str, str]:
    """`ns/x:1` / `x:1` (one's own) → (repo, tag); a ref without a version is refused."""
    repo, sep, tag = ref.rpartition(":")
    if not sep or not repo or "/" in tag:
        msg = f"у «{ref}» нет версии — назовите её: {ref}:1"
        raise RuntimeError(msg)
    if "/" not in repo:
        repo = f"{user}/{repo}"
    return repo, tag


def _list(api: CourseApi, out: TextIO) -> int:
    for r in api.call("GET", "/courses").get("courses", []):
        role = f" · {r['role']}" if r.get("role") else ""
        out.write(f"{r['ref']:<28} {r.get('title', '')}{role}\n")
    return 0


def _create(api: CourseApi, words: list[str], opts: dict[str, str], out: TextIO) -> int:
    if len(words) != 1:
        msg = "hashpass course new <имя> [--title Название] [--private]"
        raise RuntimeError(msg)
    body = {"name": words[0], "title": opts.get("title", words[0]),
            "visibility": opts.get("visibility", "public")}
    made = api.call("POST", "/courses", body)
    out.write(f"создан курс {made['ref']} «{made.get('title', '')}»\n")
    return 0


def _show(api: CourseApi, ref: str, out: TextIO) -> int:
    view = _view(api, ref)
    out.write(f"{ref} — {view.get('title', '')}\n")
    for b in view.get("blocks", []):
        out.write(f"\n{b['name']}\n")
        out.writelines(f"  {t['ref']}\n" for t in b["tasks"])
    return 0


def _add_block(api: CourseApi, _user: str, ref: str, rest: list[str], out: TextIO) -> int:
    name = " ".join(rest[2:]).strip()
    if not name:
        msg = "hashpass course <курс> add block <имя>"
        raise RuntimeError(msg)
    if any(str(b["name"]).casefold() == name.casefold() for b in _view(api, ref).get("blocks", [])):
        out.write(f"блок «{name}» уже есть\n")
        return 0
    api.call("POST", f"{_path(ref)}/blocks", {"name": name})
    out.write(f"добавлен блок «{name}»\n")
    return 0


def _rm_block(api: CourseApi, _user: str, ref: str, rest: list[str], out: TextIO) -> int:
    block = _block(_view(api, ref), " ".join(rest[2:]))
    api.call("DELETE", f"{_path(ref)}/blocks/{block['id']}")
    out.write(f"удалён блок «{block['name']}»\n")
    return 0


def _block_add(api: CourseApi, user: str, ref: str, rest: list[str], out: TextIO) -> int:
    """`block <B> add <ref>…`: new tasks go to the end of B; one already in the course moves there."""
    wanted = [_task_ref(user, raw) for raw in rest[3:]]      # every ref has its version, before asking
    view = _view(api, ref)
    block = _block(view, rest[1])
    for repo, tag in wanted:
        task = f"{repo}:{tag}"
        where = next((b for b in view["blocks"] for t in b["tasks"] if t["ref"] == task), None)
        if where is None:
            api.call("POST", f"{_path(ref)}/tasks", {"repo": repo, "tag": tag, "block_id": block["id"]})
            out.write(f"добавлено {task} → «{block['name']}»\n")
        elif where["id"] == block["id"]:
            out.write(f"{task} уже в блоке «{block['name']}»\n")
        else:
            layout = [{"id": b["id"], "tasks": [t["ref"] for t in b["tasks"] if t["ref"] != task]
                       + ([task] if b["id"] == block["id"] else [])} for b in view["blocks"]]
            api.call("PUT", f"{_path(ref)}/layout", {"blocks": layout})
            out.write(f"{task} перенесено из «{where['name']}» в «{block['name']}»\n")
        view = _view(api, ref)
    return 0


def _block_rm(api: CourseApi, user: str, ref: str, rest: list[str], out: TextIO) -> int:
    wanted = [_task_ref(user, raw) for raw in rest[3:]]
    _block(_view(api, ref), rest[1])                  # the block named must exist
    for repo, tag in wanted:
        api.call("DELETE", f"{_path(ref)}/tasks/{repo}:{tag}")
        out.write(f"убрано {repo}:{tag}\n")
    return 0


def _block_rename(api: CourseApi, _user: str, ref: str, rest: list[str], out: TextIO) -> int:
    block = _block(_view(api, ref), rest[1])
    name = " ".join(rest[3:]).strip()
    api.call("PUT", f"{_path(ref)}/blocks/{block['id']}", {"name": name})
    out.write(f"блок «{block['name']}» → «{name}»\n")
    return 0


def _set(api: CourseApi, _user: str, ref: str, rest: list[str], out: TextIO) -> int:
    if len(rest) < 3 or rest[1] not in _SETTINGS:  # noqa: PLR2004
        msg = "hashpass course <курс> set title|description|visibility|name <значение>"
        raise RuntimeError(msg)
    value = " ".join(rest[2:])
    said = api.call("PUT", _path(ref), {rest[1]: value})
    if rest[1] == "name":
        out.write(f"{ref} → {said.get('ref', '')}: курс теперь здесь, старого адреса больше нет\n")
        return 0
    out.write(f"{ref}: {rest[1]} = {value}\n")
    return 0


_Action = Callable[[CourseApi, str, str, list[str], TextIO], int]
# keyed by the first two words after the course, or by (first, third) for `block <B> <verb>`
_ACTIONS: dict[tuple[str, str], _Action] = {
    ("add", "block"): _add_block,
    ("rm", "block"): _rm_block,
    ("block", "add"): _block_add,
    ("block", "rm"): _block_rm,
    ("block", "rename"): _block_rename,
    ("set", "title"): _set,
    ("set", "description"): _set,
    ("set", "visibility"): _set,
    ("set", "name"): _set,
}
