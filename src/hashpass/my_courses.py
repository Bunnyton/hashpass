"""
The student's courses on this machine (spec 2026-10-21 §9): which ones were added, which is current.

`<home>/courses.json` = {pool key: {"current": "owner/name", "mine": ["owner/name", ...]}}. The
current course is what every client of that pool reads tasks and gets credit through
(`remote.use_course`). A course link is `https://<pool>/c/<owner>/<name>[?invite=<token>]`.
"""
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from hashpass.imagestore.store import registry_key
from hashpass.registry.remote import use_course

_LINK = re.compile(r"^/c/(?P<owner>[^/]+)/(?P<name>[a-z0-9][a-z0-9-]*)/?$")


def _path(root: Path) -> Path:
    return Path(root) / "courses.json"


def _load(root: Path) -> dict[str, dict]:
    try:
        data = json.loads(_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(root: Path, data: dict[str, dict]) -> None:
    Path(root).mkdir(parents=True, exist_ok=True)
    _path(root).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def mine(root: Path, url: str) -> list[str]:
    """Courses added on this machine for the pool at `url`, in the order they were added."""
    return list(_load(root).get(registry_key(url), {}).get("mine", []))


def current(root: Path, url: str) -> str | None:
    """Return the course the student works in on that pool, if one was chosen."""
    return _load(root).get(registry_key(url), {}).get("current") or None


def choose(root: Path, url: str, ref: str) -> None:
    """Add `ref` to the student's courses (if new) and make it current; activate it."""
    data = _load(root)
    entry = data.setdefault(registry_key(url), {"current": "", "mine": []})
    if ref not in entry["mine"]:
        entry["mine"].append(ref)
    entry["current"] = ref
    _save(root, data)
    use_course(url, ref)


def forget(root: Path, url: str, ref: str) -> None:
    """Drop a course from the list (the next one, if any, becomes current)."""
    data = _load(root)
    entry = data.get(registry_key(url))
    if not entry:
        return
    entry["mine"] = [r for r in entry["mine"] if r != ref]
    if entry.get("current") == ref:
        entry["current"] = entry["mine"][0] if entry["mine"] else ""
    _save(root, data)
    use_course(url, entry["current"] or None)


def activate(root: Path, url: str) -> str | None:
    """Make this process work in the saved current course of `url`; return it."""
    ref = current(root, url) if url else None
    if url:
        use_course(url, ref)
    return ref


def parse_link(link: str) -> tuple[str, str, str]:
    """Split a course link into (pool url, `owner/name`, invite token or '')."""
    raw = link.strip()
    parts = urlsplit(raw if "://" in raw else f"https://{raw}")
    m = _LINK.match(parts.path)
    if not parts.netloc or m is None:
        msg = (f"это не ссылка на курс: {link} — нужна вида https://<пул>/c/<владелец>/<курс> "
               "(её даёт страница курса)")
        raise ValueError(msg)
    invite = (parse_qs(parts.query).get("invite") or [""])[0]
    return f"{parts.scheme}://{parts.netloc}", f"{m.group('owner')}/{m.group('name')}", invite
