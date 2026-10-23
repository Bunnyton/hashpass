"""
Pool registry HTTP server (Flask + werkzeug WSGI): image/task blobs + auth + roles + registration.

Binds a configurable host (default loopback). It holds the signing secret and the password
hashes, so every mutating or credit-granting request requires a valid bearer token, and role-gated
endpoints check the caller's role. It may be self-hosted as the pool; it must still NEVER be pointed
at or used to touch the legacy server (no 185.x).
"""
import contextlib
import functools
import hashlib
import html
import json
import os
import re
import shutil
import socket
import ssl
import tarfile
import threading
import time
import uuid
import zoneinfo
from collections.abc import Callable, Iterable
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote, unquote

from flask import Flask, Response, g, request, send_file
from werkzeug.serving import WSGIRequestHandler
from werkzeug.serving import make_server as _wsgi_make_server

from hashpass.imagestore.store import ImageStore, did_you_mean
from hashpass.key import global_key
from hashpass.registry import courses as course_model
from hashpass.registry import era
from hashpass.registry.access import can
from hashpass.registry.approved import ApprovedStore
from hashpass.registry.attachments import AttachmentStore, safe_filename
from hashpass.registry.attempt_store import AttemptStore, SeqMismatch
from hashpass.registry.blob import inspect_image_blob, pack_image, pack_task, unpack_task
from hashpass.registry.catalog import Catalog, CatalogEntry
from hashpass.registry.config import ServerConfig, save_config
from hashpass.registry.course_api import CourseApi
from hashpass.registry.course_web import CourseWeb
from hashpass.registry.merges import MergeRequests, tree_diff
from hashpass.registry.passwords import (
    LOGIN_RE,
    LOGIN_RULE,
    ROLES,
    UserStore,
    WeakPasswordError,
    validate_password,
)
from hashpass.registry.pool_settings import PoolSettings
from hashpass.registry.progress_store import ProgressStore
from hashpass.registry.reference import reference_commands
from hashpass.registry.refs import closure_refs
from hashpass.registry.revisions import (
    REPO_ROLES,
    RepoIndex,
    check_tag,
    parse_version,
    revision_version,
)
from hashpass.registry.search_web import SearchWeb
from hashpass.registry.sources import SourceStore
from hashpass.registry.staging import Staging, new_staging, sweep_stale
from hashpass.registry.token import issue_token, verify_token
from hashpass.registry.web import (
    render_catalog,
    render_compare,
    render_dashboard,
    render_engine_install_script,
    render_front,
    render_history,
    render_history_live,
    render_image_card,
    render_install_script,
    render_login,
    render_profile,
    render_reset_form,
    render_reset_link,
    render_settings,
    render_source_file,
    render_users,
)
from hashpass.taskdigest import task_digest

_BEARER = "Bearer "
_MAX_BODY = 512 * 1024 * 1024  # cap request bodies to avoid memory blowup
_USER_RE = LOGIN_RE  # safe as a login + a per-user progress filename
_AUTHOR_ROLES = ("author", "admin")


@functools.cache
def _time_zones() -> list[str]:
    """IANA zones a viewer may pick on the settings page (zone/city names, sorted)."""
    return sorted(z for z in zoneinfo.available_timezones() if "/" in z and not z.startswith("Etc/"))
_MAX_COMMENT = 500
_MAX_MESSAGE = 2000          # a version's «what changed» (spec 2026-10-23 §3)
AUTHOR, MAINTAINER, OWNER = 1, 2, 3   # levels in an image (spec 2026-10-23 §2); 0 member, -1 nobody
_MAX_REASON = 500                # a rejection reason, shown to the author
_REJECTED_BLOCK = "rejected"     # the virtual block of rejected tasks (author + admin)
_STUDENT_FIELDS = frozenset(("number", "name", "version", "digest", "ref", "block_id",
                             "block_name", "available", "hidden", "block_open"))
_MAX_ATTACH = 8 * 1024 * 1024   # per-file attachment cap (8 MiB)
_MAX_HISTORY = 500              # command-history entries kept per submission
_MAX_CMD = 1000                 # per-command length kept
_AUTH_VERDICTS = ("typed", "pasted", "unknown")
_RESET_PREFIX = "reset:"                 # a reset token's subject; never a real login
_RESET_TTL = 2 * 24 * 60 * 60            # password-reset links live 2 days


def _now() -> str:
    """UTC timestamp (ISO-8601, second precision) for progress records."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    """
    Minimal multipart/form-data parser: return (text fields, file parts {name:(filename, bytes)}).

    Retained for the tier1 unit test that exercises it. Runtime uploads go through Flask's
    (werkzeug's) native multipart parser instead of this hand-rolled one.
    """
    match = re.search(r"boundary=([^;]+)", content_type)
    if not match:
        return {}, {}
    delim = b"--" + match.group(1).strip().strip('"').encode("utf-8", "replace")
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    for raw in body.split(delim):
        part = raw[2:] if raw.startswith(b"\r\n") else raw
        if part.endswith(b"\r\n"):
            part = part[:-2]
        head, sep, content = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        head_s = head.decode("utf-8", "replace")
        name = re.search(r'name="([^"]*)"', head_s)
        if name is None:
            continue
        filename = re.search(r'filename="([^"]*)"', head_s)
        if filename is not None:
            files[name.group(1)] = (filename.group(1), content)
        else:
            fields[name.group(1)] = content.decode("utf-8", "replace")
    return fields, files


def _sanitize_history(raw: object) -> list[dict[str, object]] | None:
    """Coerce client-supplied command history into a safe, capped list (or None)."""
    if not isinstance(raw, list):
        return None
    out: list[dict[str, object]] = []
    for item in raw[:_MAX_HISTORY]:
        if not isinstance(item, dict):
            continue
        typing = item.get("typing")
        out.append({"command": str(item.get("command", ""))[:_MAX_CMD],
                    "ts": str(item.get("ts", ""))[:64],
                    "typing": float(typing) if isinstance(typing, (int, float)) else None,
                    "pasted": bool(item.get("pasted", False))})
    return out


def _sanitize_authenticity(raw: object) -> dict[str, object] | None:
    """Coerce the client-supplied anti-bot summary into a safe {verdict, typed, pasted} (or None)."""
    if not isinstance(raw, dict):
        return None
    verdict = str(raw.get("verdict", "unknown"))
    return {"verdict": verdict if verdict in _AUTH_VERDICTS else "unknown",
            "typed": int(raw["typed"]) if isinstance(raw.get("typed"), (int, float)) else 0,
            "pasted": int(raw["pasted"]) if isinstance(raw.get("pasted"), (int, float)) else 0}


def _check_image_ref(info, name: str, version: str) -> None:
    """Reject an uploaded blob whose declared meta.json name/version differs from the PUT URL."""
    if (info.name, info.version) != (name, version):
        msg = "meta name/version does not match the URL"
        raise ValueError(msg)


def _owner_of(name: str) -> str | None:
    """Return the namespace segment of an image name (`bunnyton/cp-more` -> 'bunnyton'); None if there is none."""
    head, sep, _rest = name.partition("/")
    return head if sep else None


def _ownership_message(name: str) -> str:
    """Return the Russian 403 reason for `name`: no namespace -> admin-only; else -> wrong-author."""
    owner = _owner_of(name)
    if owner is None:
        return f"образ без пространства имён («{name}») может публиковать только администратор"
    return f"образ принадлежит другому автору («{owner}»); войдите под ним: hashpass login"


_LAYOUT_ADMIN_ONLY = ("раскладку каталога меняет только администратор; своё задание автор "
                     "добавляет/убирает через карточку")


class DeletionRequests:
    """Owners' requests to delete a revision someone else's course uses (spec §2.7): admin decides."""

    def __init__(self, path: Path) -> None:
        """Open the request list at `path`."""
        self._path = Path(path)

    def all(self) -> list[dict]:
        try:
            return list(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return []

    def _save(self, rows: list[dict]) -> None:
        self._path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def open(self, ref: str, *, by: str, courses: list[str]) -> dict:
        rows = self.all()
        mine = next((r for r in rows if r["ref"] == ref and r["state"] == "open"), None)
        if mine is not None:
            return mine
        row = {"id": f"d-{uuid.uuid4().hex[:8]}", "ref": ref, "by": by, "courses": courses,
               "state": "open", "at": time.time(), "decided_by": ""}
        self._save([*rows, row])
        return row

    def set_state(self, rid: str, state: str, by: str) -> dict | None:
        rows = self.all()
        row = next((r for r in rows if r["id"] == rid and r["state"] == "open"), None)
        if row is None:
            return None
        row.update({"state": state, "decided_by": by})
        self._save(rows)
        return row


_COPY = "approved-copy:"      # `_view_revision` result: the pre-revision approved copy of a ref


def _local_path(url: str) -> str:
    """Return a same-site path to come back to after login (`/c/x?invite=…`); anything else -> ''."""
    url = unquote(url)
    return url if url.startswith("/") and not url.startswith("//") and "\\" not in url else ""


def _tag_ref(ref: str) -> str:
    """Return a revision ref as its tag (`x:1_v3` -> `x:1`), for clients that predate revisions."""
    name, _, version = ref.partition(":")
    return f"{name}:{parse_version(version)[0]}"


def _tree_digest(path: Path) -> str | None:
    """Content digest of a directory (paths + bytes), None if there is none."""
    return task_digest(path) if path.is_dir() else None


class PoolServer:
    """Pool registry state (stores, secret, config) + a Flask WSGI app wired to it."""

    def __init__(self, *, store: ImageStore, users: UserStore, secret: bytes,   # noqa: PLR0913
                 config: ServerConfig | None = None,
                 config_path: Path | None = None, catalog_path: Path | None = None,
                 progress_path: Path | None = None, attachments_path: Path | None = None) -> None:
        """Wire stores + HMAC secret + on-disk paths into a Flask WSGI app built by `_build_app`."""
        self.store = store
        self.users = users
        self.secret = secret
        self.config = config or ServerConfig()
        self.config_path = config_path
        self.catalog_path = catalog_path
        self.progress_path = progress_path
        self.attachments_path = attachments_path
        self.app = self._build_app()

    def catalog(self) -> Catalog:
        return Catalog(self.catalog_path or (Path(self.store.root) / "catalog.json"))

    def repo(self, name: str) -> RepoIndex:
        """Open the tags + revisions index of repository `name` (spec 2026-10-21 §2)."""
        return RepoIndex(Path(self.store.root) / ".repos", name)

    def resolve(self, name: str, version: str) -> str | None:
        """
        Resolve a requested version to the stored ref that serves it, or None.

        `tag_vN` -> that revision; `tag` / `tag_latest` -> the tag's newest revision. A version
        with no revisions but a stored record of its own (a pool not yet migrated) is itself.
        """
        tag, n, _latest = parse_version(version)
        idx = self.repo(name)
        rev = idx.get(tag, n) if n is not None else idx.latest(tag)
        if rev is not None:
            ref = f"{name}:{revision_version(tag, rev.n)}"
            return ref if self.store.exists(ref) else None
        if n is None and self.store.exists(f"{name}:{version}"):
            return f"{name}:{version}"
        return None

    def pool_settings(self) -> PoolSettings:
        """Pool-wide switches (auto-approval), next to the catalog."""
        return PoolSettings((self.catalog_path or (Path(self.store.root) / "catalog.json")).parent
                            / "pool-settings.json")

    def _fresh_for(self, user: str | None, name: str) -> bool:
        """Whether `user` gets a task's latest push: its people (spec 2026-10-23 §2) or an admin."""
        return self._repo_level(user, name) >= 0

    def _image_digest(self, ref: str) -> str:
        """Return the image digest of `ref` (a tag means its newest revision); '' if there is none."""
        name, _, version = ref.partition(":")
        live = self.resolve(name, version or "latest")
        try:
            return (self.store.get(live).digest or "") if live else ""
        except KeyError:
            return ""

    def _approved_rev(self, entry: CatalogEntry) -> str | None:
        """
        Return the revision students get for a catalogued tag.

        The newest one holding the approved task (and the approved image, when one is pinned);
        None if nothing was ever approved.
        """
        if not entry.approved_digest:
            return None
        name, _, tag = entry.ref.partition(":")
        for rev in reversed(self.repo(name).revisions(tag)):
            if rev.task_digest == entry.approved_digest and (
                    not entry.approved_image or rev.image_digest == entry.approved_image):
                ref = f"{name}:{revision_version(tag, rev.n)}"
                return ref if self.store.exists(ref) else None
        if self.store.exists(entry.ref):              # a pool not yet moved to revisions
            img = self.store.get(entry.ref)
            task = img.layer.parent / "task"
            if (task.is_dir() and task_digest(task) == entry.approved_digest
                    and (not entry.approved_image or img.digest == entry.approved_image)):
                return entry.ref
            copies = ApprovedStore(Path(self.store.root) / "approved")
            if copies.task_digest(entry.ref) == entry.approved_digest and copies.blob(entry.ref):
                return _COPY + entry.ref              # an update waits: students keep the copy
        return None

    def _view_revision(self, user: str | None, name: str, version: str) -> str | None:  # noqa: PLR0911
        """
        Which stored revision `user` gets for `name:version`, or None (not found / not for them).

        Its author and admins get what they ask for (a tag -> its newest revision); everyone else
        gets the approved revision of a catalogued tag, any revision of a plain image (a base),
        and nothing of a task outside the catalog.
        """
        resolved = self.resolve(name, version)
        if resolved is None:
            return None
        if self._fresh_for(user, name):
            return resolved
        tag, n, _latest = parse_version(version)
        hit = self._course_revision(user, name, tag, n, action="view")
        if hit is not None:                       # a course the caller may see holds it (anyone: public)
            ref = f"{name}:{revision_version(tag, hit[1])}"
            return ref if self.store.exists(ref) else None
        if self.repo(name).visibility == "private":
            return resolved if self._reachable_in_course(user, resolved) else None
        if self.default_course() is not None:      # moved to courses: no catalog any more
            is_task = (self.store.get(resolved).layer.parent / "task").exists()
            return None if is_task else resolved
        entry = self.catalog().find(f"{name}:{tag}")
        if entry is None:
            return None if (self.store.get(resolved).layer.parent / "task").exists() else resolved
        approved = self._approved_rev(entry)
        if n is not None:
            return resolved if resolved == approved else None
        return approved

    def _live_ref(self, ref: str) -> str:
        """Return a ref as stored: a tag -> its newest revision; anything unresolvable -> itself."""
        name, _, version = ref.partition(":")
        return (self.resolve(name, version) if name and version else None) or ref

    def _course_revision(self, user: str | None, repo: str, tag: str, n: int | None,  # noqa: PLR0913
                         course_ref: str | None = None, *,
                         action: str = "play") -> tuple["course_model.Course", int] | None:
        """
        Return (course, revision) through which `user` gets `repo:tag` (spec §9), or None.

        The course is `?course=owner/name` when given, else the first course the caller may play
        holding the tag. A requested `_vN` must be the course's current revision of it. Reading
        needs only `view` (a public course's tasks download without a token, as before courses);
        credit needs `play`.
        """
        role = self.users.role(user) if user else None
        wanted = course_ref or (request.args.get("course") if request else None)
        store = self.course_api.courses
        candidates = [c for c in ([store.get(wanted)] if wanted else store.courses_with(repo, tag)) if c]
        for course in candidates:
            task = course.find_task(repo, tag)
            if task is None or not can(user, role, course, action):
                continue
            latest = self.repo(repo).latest(tag)
            eff = course_model.effective_n(course, task, latest=latest.n if latest else None)
            if n is None or n == eff:
                return course, eff
        return None

    def _reachable_in_course(self, user: str | None, ref: str) -> bool:
        """Whether a private image `ref` is a parent/base of a task `user` gets through a course."""
        role = self.users.role(user) if user else None
        for course in self.course_api.courses.all():
            if not can(user, role, course, "play"):
                continue
            for _block, task in course.tasks():
                latest = self.repo(task["repo"]).latest(task["tag"])
                eff = course_model.effective_n(course, task, latest=latest.n if latest else None)
                top = f"{task['repo']}:{revision_version(task['tag'], eff)}"
                with contextlib.suppress(KeyError):
                    chain = closure_refs(top, self.store)
                    bases = [b for r in chain if (b := self.store.get(r).base)]
                    if ref in chain or ref in bases:
                        return True
        return False

    def _tag_revisions(self, ref_tag: str) -> list[str]:
        """Every stored revision of a tag (plus an unmigrated record under the tag itself)."""
        name, _, tag = ref_tag.partition(":")
        refs = [f"{name}:{revision_version(tag, r.n)}" for r in self.repo(name).revisions(tag)]
        if self.store.exists(ref_tag):
            refs.append(ref_tag)
        return refs

    def _delete_task(self, ref: str) -> None:
        """Remove a tag from the pool entirely: every revision (blob, task/, sources, files) + entry."""
        name, _, tag = ref.partition(":")
        self.catalog().remove_task(ref)
        revisions = self._tag_revisions(ref)
        with self.repo(name).locked() as idx:
            for rev in idx.revisions(tag):
                idx.remove(tag, rev.n)
        for rev_ref in revisions:
            r_name, _, r_version = rev_ref.partition(":")
            self.sources().remove(rev_ref)
            with contextlib.suppress(ValueError, OSError):
                shutil.rmtree(self.attachments().ref_path(rev_ref), ignore_errors=True)
            with contextlib.suppress(ValueError, OSError):
                shutil.rmtree(self.store.dir(r_name, r_version), ignore_errors=True)

    def _purge_rejected(self) -> None:
        """
        Settle rejections a week old: a never-approved task leaves the catalog, an approved one goes back.

        Spec: «хранятся неделю, потом удаляются»; review 2026-10-14: a rejected UPDATE of a course
        task must not take the task away from students -- the task returns to its approved version.
        The revisions themselves stay (immutable); only the catalog changes.
        """
        now = time.time()
        for ref in self.catalog().expired_rejected(now):
            entry = self.catalog().find(ref)
            approved = self._approved_rev(entry) if entry else None
            image = (self.store.get(approved).digest or "") if approved and not approved.startswith(_COPY) else ""
            self.catalog().restore_approved(ref, entry.approved_image if entry and entry.approved_image else image)
        for ref in self.catalog().purge_rejected(now):
            self.catalog().remove_task(ref)

    def _auto_approved(self, name: str) -> bool:
        """Whether a push of `name` approves itself: the pool's switch or its author's flag."""
        owner = _owner_of(name)
        return self.pool_settings().auto_approve or bool(owner and self.users.auto_approve(owner))

    def progress(self) -> ProgressStore:
        return ProgressStore(self.progress_path or (Path(self.store.root) / "progress"))

    def attempts(self) -> AttemptStore:
        """Console sessions (commands + output), next to the progress dir."""
        base = Path(self.progress_path).parent if self.progress_path else Path(self.store.root)
        return AttemptStore(base / "attempts")

    def attachments(self) -> AttachmentStore:
        return AttachmentStore(self.attachments_path or (Path(self.store.root) / "attachments"))

    def _sources_ready(self, ref: str) -> bool:
        """
        Whether `ref` has a source tree -- unpacking an attached source.tar.gz if needed.

        Tasks pushed before sources were kept as files (the whole course on prod, 2026-10-14) have
        only the archive attachment; the first look turns it into files.
        """
        src = self.sources()
        if src.listing(ref):
            return True
        try:
            src.put_archive(ref, self.attachments().read_file(ref, "source.tar.gz"))
        except (ValueError, OSError, tarfile.TarError):
            return False
        return bool(src.listing(ref))

    def sources(self) -> SourceStore:
        """Open the store of task sources as files (authors/admins read, the namespace owner writes)."""
        return SourceStore(Path(self.store.root) / "sources")

    # -- Flask app + route wiring --------------------------------------------

    def _build_app(self) -> Flask:
        here = Path(__file__).parent
        app = Flask("hashpass.registry",
                    static_folder=str(here / "static"),
                    static_url_path="/static")
        app.config["MAX_CONTENT_LENGTH"] = _MAX_BODY
        app.url_map.strict_slashes = False
        self._register_routes(app)
        self.course_api = CourseApi(self)
        self.course_api.register(app)
        CourseWeb(self).register(app)
        self.people = SearchWeb(self)
        self.people.register(app)
        app.before_request(self._legacy_catalog_gone)
        return app

    def _register_routes(self, app: Flask) -> None:  # noqa: PLR0915  (one line per route)
        # public / installers
        app.add_url_rule("/", "root", self._route_front, methods=["GET"])
        app.add_url_rule("/install.sh", "install_sh", self._route_install_sh, methods=["GET"])
        app.add_url_rule("/install-engine.sh", "install_engine_sh",
                         self._route_install_engine_sh, methods=["GET"])
        # bearer-token endpoints for the student/author client
        app.add_url_rule("/login", "login", self._route_login, methods=["POST"])
        app.add_url_rule("/register", "register", self._route_register, methods=["POST"])
        app.add_url_rule("/admin/registration", "admin_registration",
                         self._route_admin_registration, methods=["POST"])
        app.add_url_rule("/admin/role", "admin_role", self._route_admin_role, methods=["POST"])
        app.add_url_rule("/submit", "submit", self._route_submit, methods=["POST"])
        app.add_url_rule("/attempt", "attempt", self._route_attempt, methods=["POST"])
        app.add_url_rule("/solutions", "solutions", self._route_solutions, methods=["GET"])
        app.add_url_rule("/solution/<path:ref>", "solution", self._route_solution, methods=["GET"])
        app.add_url_rule("/me", "me", self._route_me, methods=["GET"])
        app.add_url_rule("/users/search", "user_search", self._route_user_search, methods=["GET"])
        app.add_url_rule("/users/<user>/exists", "user_exists",
                         self._route_user_exists, methods=["GET"])
        app.add_url_rule("/catalog", "catalog_api", self._route_catalog, methods=["GET"])
        app.add_url_rule("/catalog/layout", "catalog_layout_api", self._route_catalog_layout,
                         methods=["PUT"])
        app.add_url_rule("/catalog/hidden", "catalog_hidden_api", self._route_catalog_hidden,
                         methods=["PUT"])
        app.add_url_rule("/catalog/move", "catalog_move_api", self._route_catalog_move,
                         methods=["PUT"])
        app.add_url_rule("/catalog/block", "catalog_block_api", self._route_catalog_block,
                         methods=["PUT"])
        app.add_url_rule("/progress", "progress_api", self._route_progress, methods=["GET"])
        app.add_url_rule("/images", "images_api", self._route_images, methods=["GET"])
        # blobs (name may be multi-segment; last segment is the version)
        app.add_url_rule("/image/<path:tail>", "image_blob", self._route_image_blob,
                         methods=["GET", "HEAD", "PUT"])
        app.add_url_rule("/task/<path:tail>", "task_blob", self._route_task_blob,
                         methods=["GET", "PUT", "DELETE"])
        app.add_url_rule("/catalog/approve", "catalog_approve", self._route_catalog_approve,
                         methods=["POST"])
        app.add_url_rule("/catalog/reject", "catalog_reject", self._route_catalog_reject,
                         methods=["POST"])
        app.add_url_rule("/pool/settings", "pool_settings", self._route_pool_settings,
                         methods=["GET", "PUT"])
        app.add_url_rule("/users/<user>/auto-approve", "user_auto_approve",
                         self._route_user_auto_approve, methods=["PUT"])
        app.add_url_rule("/closure/<path:tail>", "closure", self._route_closure, methods=["GET"])
        app.add_url_rule("/web/compare/<path:name>", "web_compare", self._web_compare, methods=["GET"])
        app.add_url_rule("/repo-members/<path:tail>", "repo_members", self._route_repo_members,
                         methods=["PUT", "DELETE"])
        app.add_url_rule("/deletion-requests", "deletion_requests", self._route_deletions,
                         methods=["GET"])
        app.add_url_rule("/deletion-requests/<rid>", "deletion_request", self._route_deletion,
                         methods=["POST"])
        app.add_url_rule("/revisions/<path:tail>", "revisions", self._route_revisions,
                         methods=["GET", "POST", "PUT", "DELETE"])
        app.add_url_rule("/attachment/<path:tail>", "attachment_put",
                         self._route_attachment_put, methods=["PUT"])
        app.add_url_rule("/attachment/<path:tail>", "attachment_get",
                         self._route_attachment_get, methods=["GET"])
        app.add_url_rule("/source/<path:tail>", "source", self._route_source,
                         methods=["GET", "PUT"])
        # web dashboard (cookie session)
        app.add_url_rule("/web", "web_dashboard", self._web_dashboard, methods=["GET"])
        app.add_url_rule("/web/login", "web_login_get", self._web_login_get, methods=["GET"])
        app.add_url_rule("/web/login", "web_login_post", self._web_login_post, methods=["POST"])
        app.add_url_rule("/web/logout", "web_logout", self._web_logout, methods=["GET"])
        app.add_url_rule("/web/users", "web_users", self._web_users, methods=["GET"])
        app.add_url_rule("/web/users/auto-approve", "web_users_auto_approve",
                         self._web_users_auto_approve, methods=["POST"])
        app.add_url_rule("/web/pool/auto-approve", "web_pool_auto_approve",
                         self._web_pool_auto_approve, methods=["POST"])
        app.add_url_rule("/web/users/role", "web_users_role",
                         self._web_users_role, methods=["POST"])
        app.add_url_rule("/web/users/group", "web_users_group",
                         self._web_users_group, methods=["POST"])
        app.add_url_rule("/web/users/comment", "web_users_comment",
                         self._web_users_comment, methods=["POST"])
        app.add_url_rule("/web/users/registration", "web_users_registration",
                         self._web_users_registration, methods=["POST"])
        app.add_url_rule("/web/users/reset", "web_users_reset",
                         self._web_users_reset_link, methods=["POST"])
        app.add_url_rule("/web/users/delete", "web_users_delete",
                         self._web_users_delete, methods=["POST"])
        app.add_url_rule("/web/users/delete-group", "web_users_delete_group",
                         self._web_users_delete_group, methods=["POST"])
        app.add_url_rule("/web/user/<path:login>", "web_user_profile",
                         self._web_user_profile, methods=["GET"])
        app.add_url_rule("/web/settings", "web_settings", self._web_password_get, methods=["GET"])
        app.add_url_rule("/web/settings/tz", "web_settings_tz",
                         self._web_settings_tz, methods=["POST"])
        app.add_url_rule("/web/password", "web_password_get",
                         self._web_password_get, methods=["GET"])
        app.add_url_rule("/web/password", "web_password_post",
                         self._web_password_post, methods=["POST"])
        app.add_url_rule("/web/reset", "web_reset_get", self._web_reset_get, methods=["GET"])
        app.add_url_rule("/web/reset", "web_reset_post", self._web_reset_post, methods=["POST"])
        app.add_url_rule("/web/images", "web_images", self._web_images, methods=["GET"])
        app.add_url_rule("/web/image/<path:ref>", "web_image_card",
                         self._web_image_card, methods=["GET"])
        app.add_url_rule("/web/images/file", "web_image_file",
                         self._web_image_file, methods=["GET"])
        app.add_url_rule("/web/images/attach", "web_image_attach",
                         self._web_image_attach, methods=["POST"])
        app.add_url_rule("/web/images/source", "web_source_file", self._web_source_file,
                         methods=["GET"])
        app.add_url_rule("/web/images/source-archive", "web_source_archive",
                         self._web_source_archive, methods=["GET"])
        app.add_url_rule("/web/images/attach-delete", "web_image_attach_delete",
                         self._web_image_attach_delete, methods=["POST"])
        app.add_url_rule("/web/history", "web_history", self._web_history, methods=["GET"])
        app.add_url_rule("/web/history/live", "web_history_live", self._web_history_live,
                         methods=["GET"])
        app.add_url_rule("/web/catalog/add", "web_catalog_add",
                         self._web_catalog_add, methods=["POST"])
        app.add_url_rule("/web/catalog/remove", "web_catalog_remove",
                         self._web_catalog_remove, methods=["POST"])
        app.add_url_rule("/web/catalog/layout", "web_catalog_layout",
                         self._web_catalog_layout, methods=["POST"])
        app.add_url_rule("/web/tasks/toggle", "web_task_toggle",
                         self._web_task_toggle, methods=["POST"])
        app.add_url_rule("/web/blocks/add", "web_block_add",
                         self._web_block_add, methods=["POST"])
        app.add_url_rule("/web/blocks/rename", "web_block_rename",
                         self._web_block_rename, methods=["POST"])
        app.add_url_rule("/web/blocks/remove", "web_block_remove",
                         self._web_block_remove, methods=["POST"])
        app.add_url_rule("/web/blocks/toggle", "web_block_toggle",
                         self._web_block_toggle, methods=["POST"])
        app.add_url_rule("/web/blocks/hide-tasks", "web_block_hide_tasks",
                         self._web_block_hide_tasks, methods=["POST"])

    # -- response helpers ---------------------------------------------------

    @staticmethod
    def _empty(status: HTTPStatus) -> Response:
        resp = Response(b"", status=int(status))
        resp.headers["Content-Length"] = "0"
        return resp

    @staticmethod
    def _json(status: HTTPStatus, payload: dict) -> Response:
        return Response(json.dumps(payload), status=int(status), mimetype="application/json")

    @staticmethod
    def _blob(status: HTTPStatus, blob: bytes) -> Response:
        return Response(blob, status=int(status), mimetype="application/octet-stream")

    @staticmethod
    def _html(body: str, status: HTTPStatus = HTTPStatus.OK) -> Response:
        return Response(body, status=int(status), mimetype="text/html; charset=utf-8")

    @staticmethod
    def _serve_script(body: str) -> Response:
        return Response(body, status=200, mimetype="text/x-shellscript; charset=utf-8")

    @staticmethod
    def _redirect(location: str, *, clear_cookie: bool = False,
                  set_cookie: tuple[str, str] | None = None) -> Response:
        resp = Response(b"", status=int(HTTPStatus.SEE_OTHER))
        resp.headers["Location"] = location
        resp.autocorrect_location_header = False   # keep the raw path (tests check the exact string)
        resp.headers["Content-Length"] = "0"
        if clear_cookie:
            resp.set_cookie("hp_session", "", max_age=0, path="/")
        if set_cookie is not None:
            name, value = set_cookie
            resp.set_cookie(name, value, path="/", httponly=True, samesite="Lax")
        return resp

    # -- auth helpers -------------------------------------------------------

    def _token_user(self) -> str | None:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith(_BEARER):
            # the web pages call the JSON API with their cookie session. A cross-site page can send
            # a plain form POST with that cookie, so a write counts the cookie only with a JSON body
            # (which, like PUT / DELETE, needs a CORS preflight this server never grants).
            if not request.cookies.get("hp_session"):
                return None
            if request.method not in ("GET", "HEAD") and not request.is_json:
                return None
            return self._session_user()
        user = verify_token(self.secret, auth[len(_BEARER):], now=time.time())
        # The HMAC token is valid till its expiry regardless of whether the account still
        # exists.  If an admin deleted the user, we treat the token as unauthenticated so
        # `/submit`, `/catalog`, `/progress`, `/me` etc. all refuse and no progress gets
        # written for a ghost login.
        if user is None or not self.users.has(user):
            return None
        return user

    def _auth_role(self, roles: tuple[str, ...]) -> tuple[str | None, HTTPStatus | None]:
        """Return (user, None) if the bearer token maps to a user in `roles`, else (None, 401/403)."""
        user = self._token_user()
        if user is None:
            return None, HTTPStatus.UNAUTHORIZED
        if self.users.role(user) not in roles:
            return None, HTTPStatus.FORBIDDEN
        return user, None

    def _repo_level(self, user: str | None, name: str) -> int:
        """
        Return `user`'s level in image `name` (spec 2026-10-23 §2).

        3 owner (its namespace, or the admin), 2 maintainer, 1 author, 0 member, -1 nobody.
        """
        if user is None:
            return -1
        if self.users.role(user) == "admin" or _owner_of(name) == user:
            return 3
        role = self.repo(name).members.get(user)
        return REPO_ROLES.index(role) if role in REPO_ROLES else -1

    def _may_write(self, user: str, name: str) -> bool:
        """Whether `user` may publish versions of image `name`: its author and up."""
        return self._repo_level(user, name) >= AUTHOR

    def _authorize_write(self, name: str, version: str) -> tuple[str | None, Response | None]:
        """
        Require author/admin + ownership of `name`'s namespace (admin-only if it has none).

        The 403 reason also names an existing twin of the ref under another namespace
        (`debian:trixie` refused -> «быть может, вы искали bunnyton/debian:trixie?»).
        """
        # any signed-in user writes into their own namespace (spec 2026-10-21 §3)
        user = self._token_user()
        if user is None:
            return None, self._empty(HTTPStatus.UNAUTHORIZED)
        if self._may_write(user, name):
            return user, None
        suggestions = self.store.similar(f"{name}:{version}")
        reason = _ownership_message(name)
        if suggestions:
            reason = f"{reason}; {did_you_mean(suggestions)}"
        return None, self._json(HTTPStatus.FORBIDDEN, {"error": reason, "suggestions": suggestions})

    def _not_found(self, ref: str) -> Response:
        """JSON 404 for an unknown ref, naming its twins under other namespaces (if any)."""
        suggestions = self.store.similar(ref)
        reason = f"образ «{ref}» не найден на пуле"
        if suggestions:
            reason = f"{reason}; {did_you_mean(suggestions)}"
        return self._json(HTTPStatus.NOT_FOUND, {"error": reason, "suggestions": suggestions})

    def _not_found_head(self, ref: str) -> Response:
        """Bodiless 404 (HEAD): the twins travel in `X-Image-Suggest`, comma-separated."""
        resp = self._empty(HTTPStatus.NOT_FOUND)
        suggestions = self.store.similar(ref)
        if suggestions:
            resp.headers["X-Image-Suggest"] = ", ".join(suggestions)
        return resp

    def _session_user(self) -> str | None:
        token = request.cookies.get("hp_session")
        if not token:
            return None
        user = verify_token(self.secret, token, now=time.time())
        # Same guard as `_token_user`: a cookie session for a deleted account
        # is treated as no session -- every `/web/*` route redirects to /web/login.
        if user is None or not self.users.has(user):
            return None
        g.hp_admin = self.users.role(user) == "admin"    # the nav shows admin pages to the admin only
        g.hp_staff = self.users.role(user) in _AUTHOR_ROLES
        g.hp_tz = str((self.users.get(user) or {}).get("tz", ""))   # pages show times in it
        g.hp_user = user                                 # the nav links one's own page (home)
        return user

    def _session_role(self, roles: tuple[str, ...]) -> str | None:
        user = self._session_user()
        if user is not None and self.users.role(user) in roles:
            return user
        return None

    def _pool_url(self) -> str:
        return f"{request.scheme}://{request.host}"

    @staticmethod
    def _split_ref(tail: str) -> tuple[str, str] | None:
        """`ns/name/version` -> ('ns/name', 'version'); at least one name segment required."""
        if "/" not in tail:
            return None
        name, version = tail.rsplit("/", 1)
        if not name or not version:
            return None
        return name, version

    # -- routes: public / installers ----------------------------------------

    def _route_front(self) -> Response:
        if era.courses_on():   # the home page is the showcase + search
            return self.people.explore()
        return self._html(render_front(self._pool_url()))

    def _route_install_sh(self) -> Response:
        return self._serve_script(render_install_script(self._pool_url()))

    def _route_install_engine_sh(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        return self._serve_script(render_engine_install_script(self._pool_url()))

    # -- routes: API auth --------------------------------------------------

    def _route_login(self) -> Response:
        creds = request.get_json(silent=True) or {}
        if not isinstance(creds, dict):
            return self._empty(HTTPStatus.BAD_REQUEST)
        user = str(creds.get("user", ""))
        if not self.users.verify(user, str(creds.get("password", ""))):
            return self._empty(HTTPStatus.UNAUTHORIZED)
        return self._json(HTTPStatus.OK,
                          {"token": issue_token(self.secret, user, now=time.time())})

    def _route_register(self) -> Response:   # noqa: PLR0911
        if not self.config.registration_open:
            return self._empty(HTTPStatus.FORBIDDEN)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return self._empty(HTTPStatus.BAD_REQUEST)
        user = str(data.get("user", "")).strip()
        password = str(data.get("password", ""))
        group = str(data.get("group", "")).strip()
        comment = str(data.get("comment", "")).strip()
        if group and not comment.startswith(group):   # spec §3: groups are gone; an old client's
            comment = f"{group} · {comment}".rstrip(" ·")   # group leads the comment (as the move does)
        comment = comment[:_MAX_COMMENT]
        # login + password are required; the comment is free metadata and may be empty
        if not _USER_RE.match(user):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": LOGIN_RULE})
        if not password:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "пароль не задан"})
        try:
            validate_password(password)
        except WeakPasswordError as exc:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        if self.users.has(user) or self.users.reserved(user):
            return self._empty(HTTPStatus.CONFLICT)
        self.users.add(user, password, role="student", group=group, comment=comment)
        return self._json(HTTPStatus.CREATED,
                          {"token": issue_token(self.secret, user, now=time.time())})

    def _route_admin_registration(self) -> Response:
        _user, err = self._auth_role(("admin",))
        if err is not None:
            return self._empty(err)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return self._empty(HTTPStatus.BAD_REQUEST)
        self.config.registration_open = bool(data.get("open", True))
        if self.config_path is not None:
            save_config(self.config_path, self.config)
        return self._json(HTTPStatus.OK,
                          {"registration_open": self.config.registration_open})

    def _route_admin_role(self) -> Response:
        actor, err = self._auth_role(("admin",))
        if err is not None:
            return self._empty(err)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return self._empty(HTTPStatus.BAD_REQUEST)
        target = str(data.get("user", ""))
        role = str(data.get("role", ""))
        if role not in ROLES:
            return self._empty(HTTPStatus.BAD_REQUEST)
        if target == actor:                          # an admin cannot change their own role
            return self._empty(HTTPStatus.FORBIDDEN)
        try:
            self.users.set_role(target, role)
        except KeyError:
            return self._empty(HTTPStatus.NOT_FOUND)
        return self._json(HTTPStatus.OK, {"user": target, "role": role})

    def _route_user_exists(self, user: str) -> Response:
        """
        Report whether this login exists on the pool (public; enumeration intentional).

        This is a teaching pool -- an attacker learning which logins are taken wins
        nothing.  The client uses the answer to skip the password prompt when the
        account clearly needs to be registered rather than logged into.
        """
        return self._json(HTTPStatus.OK, {"user": user, "exists": self.users.has(user)})

    def _route_user_search(self) -> Response:
        """Admin: find users by login or comment (where a group now lives) -- spec §3."""
        _user, err = self._auth_role(("admin",))
        if err is not None:
            return self._empty(err)
        rows = [{k: p[k] for k in ("user", "comment", "group", "role", "created_at")}
                for p in self.users.search(request.args.get("q", ""))]
        return self._json(HTTPStatus.OK, {"users": rows})

    def _route_me(self) -> Response:
        user = self._token_user()
        profile = self.users.get(user) if user is not None else None
        if profile is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        return self._json(HTTPStatus.OK, profile)

    def _route_catalog(self) -> Response:
        """
        Return the ordered catalog.

        `available` is always the STUDENT view; for an author/admin a locked task also carries
        `preview: true` -- they see its ref and may run it (no credit).
        """
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        wanted = request.args.get("course")
        if wanted and era.courses_on():    # one course, in catalog rows
            picked = self.course_api.courses.get(wanted)
            if picked is None or not can(user, self.users.role(user), picked, "view"):
                return self._json(HTTPStatus.NOT_FOUND, {"error": f"нет такого курса: {wanted}"})
            return self._json(HTTPStatus.OK, {"catalog": self._course_rows(picked, user)})
        course = self.default_course()
        if course is not None:                        # after the move to courses (spec §9)
            return self._json(HTTPStatus.OK, {"catalog": self._course_rows(course, user)})
        self._purge_rejected()
        return self._json(HTTPStatus.OK, {"catalog": self._catalog_rows(user)})

    _LEGACY_WRITES = ("/catalog/layout", "/catalog/hidden", "/catalog/move", "/catalog/block",
                      "/catalog/approve", "/catalog/reject", "/web/catalog/add", "/web/catalog/remove",
                      "/web/catalog/layout", "/web/tasks/toggle", "/web/blocks/add",
                      "/web/blocks/rename", "/web/blocks/remove", "/web/blocks/toggle",
                      "/web/blocks/hide-tasks")

    def _legacy_catalog_gone(self) -> Response | None:
        """
        Gate the course era: `/courses` only where switched on; old catalog edits 410 after the move.

        Every pool runs on courses (`era`); only the old catalog's tests switch them off.
        """
        course_era = request.path.startswith(("/courses", "/c/")) or request.path == "/c"
        if course_era and not era.courses_on():
            return self._json(HTTPStatus.NOT_FOUND, {"error": "курсы на этом пуле ещё не включены"})
        if request.path not in self._LEGACY_WRITES or self.default_course() is None:
            return None
        return self._json(HTTPStatus.GONE, {
            "error": f"раскладка и модерация теперь в курсах: курс {self.config.default_course}"})

    def default_course(self) -> "course_model.Course | None":
        """Return the course old clients (no `course`) work in, once the pool moved to courses."""
        ref = self.config.default_course
        return self.course_api.courses.get(ref) if ref else None

    def _course_rows(self, course: "course_model.Course", user: str) -> list[dict[str, object]]:
        """Return the default course in the old `/catalog` row shape, as `user` may see it."""
        role = self.users.role(user)
        if not can(user, role, course, "view"):
            return []
        staff = can(user, role, course, "moderate")
        mine = self.progress().get(user)
        rows: list[dict[str, object]] = []
        for block in course.blocks:
            for task in block["tasks"]:
                visible = block.get("open", True) and not task.get("hidden")
                if not visible and not staff:
                    continue
                latest = self.repo(task["repo"]).latest(task["tag"])
                n = course_model.effective_n(course, task, latest=latest.n if latest else None)
                rev = self.repo(task["repo"]).get(task["tag"], n)
                ref = f"{task['repo']}:{task['tag']}"
                solved = self._solved_n(mine.get(ref), task["repo"], task["tag"])
                rows.append({"number": len(rows) + 1, "name": task["repo"], "version": task["tag"],
                             "ref": ref, "digest": rev.task_digest if rev else "", "n": n,
                             "block_id": block["id"], "block_name": block["name"],
                             "available": visible, "hidden": task.get("hidden", False),
                             "block_open": block.get("open", True), "course": course.ref}
                            | ({"preview": True} if staff and not visible else {})
                            | ({"solved_n": solved} if solved else {}))
        return rows

    def _solved_n(self, rec: object, repo: str, tag: str) -> int | None:
        """Which version a credited task was solved in: recorded `n`, else found by its digest."""
        if not isinstance(rec, dict) or rec.get("status") != "passed":
            return None
        if rec.get("n"):
            return int(rec["n"])
        return next((r.n for r in self.repo(repo).revisions(tag) if r.task_digest == rec.get("digest")), None)

    def _catalog_rows(self, user: str) -> list[dict[str, object]]:
        """
        Return the catalog as `user` may see it.

        A student sees only what is open to them, at the APPROVED version (its digest). An
        author sees approved tasks (locked ones marked `preview`) and all of their own; the
        admin sees everything. Rejected tasks go to a block «Отклонённые» at the end -- for their
        author and the admin only.
        """
        role = self.users.role(user)
        staff, admin = role in _AUTHOR_ROLES, role == "admin"
        rows: list[dict[str, object]] = []
        rejected: list[dict[str, object]] = []
        for e in self.catalog().entries():
            mine = admin or e.owner == user
            if not staff:
                if e.available:                           # moderation details are not theirs
                    row = {k: v for k, v in e.as_dict().items() if k in _STUDENT_FIELDS}
                    rows.append(row | {"digest": e.approved_digest})
                continue
            if e.state == "rejected" and mine:
                rejected.append(e.as_dict() | {"preview": True, "rejected": True,
                                               "block_id": _REJECTED_BLOCK, "block_name": "Отклонённые"})
                continue
            if not (mine or e.approved_digest):
                continue                                  # someone else's, never approved
            row = e.as_dict() | ({"preview": True} if not e.available else {})
            if not mine:
                row["digest"] = e.approved_digest          # they get the approved copy
            rows.append(row)
        return rows + rejected

    def _route_catalog_approve(self) -> Response:
        """Admin: approve a task's current version -- students get it from now on."""
        _user, err = self._auth_role(("admin",))
        if err is not None:
            return self._empty(err)
        data = request.get_json(silent=True) or {}
        ref, seen = str(data.get("ref", "")), str(data.get("digest") or "")
        entry = self.catalog().find(ref)
        if entry is None:
            return self._not_found(ref)
        if seen and seen != entry.digest:             # re-pushed since the admin looked at it
            return self._json(HTTPStatus.CONFLICT, {
                "error": f"{ref} перезалили, пока вы его смотрели — обновите каталог и проверьте снова"})
        if self.catalog().approve(ref, image=self._image_digest(ref)) is None:
            return self._not_found(ref)
        return self._json(HTTPStatus.OK, {"ref": ref, "state": "approved"})

    def _route_catalog_reject(self) -> Response:
        """Admin: reject a task's current version, with an optional reason for its author."""
        _user, err = self._auth_role(("admin",))
        if err is not None:
            return self._empty(err)
        data = request.get_json(silent=True) or {}
        ref, reason = str(data.get("ref", "")), str(data.get("reason", ""))[:_MAX_REASON]
        if not self.catalog().reject(ref, reason, now=time.time()):
            return self._not_found(ref)
        return self._json(HTTPStatus.OK, {"ref": ref, "state": "rejected"})

    def _route_pool_settings(self) -> Response:
        """Admin: read / switch pool-wide auto-approval."""
        _user, err = self._auth_role(("admin",))
        if err is not None:
            return self._empty(err)
        settings = self.pool_settings()
        if request.method == "PUT":
            settings.set_auto_approve(on=bool((request.get_json(silent=True) or {}).get("auto_approve")))
        return self._json(HTTPStatus.OK, {"auto_approve": settings.auto_approve})

    def _route_user_auto_approve(self, user: str) -> Response:
        """Admin: switch one author's auto-approval (the admin's own too)."""
        _actor, err = self._auth_role(("admin",))
        if err is not None:
            return self._empty(err)
        if not self.users.has(user):
            return self._empty(HTTPStatus.NOT_FOUND)
        self.users.set_auto_approve(user, on=bool((request.get_json(silent=True) or {}).get("on")))
        return self._json(HTTPStatus.OK, {"user": user, "auto_approve": self.users.auto_approve(user)})

    def _route_catalog_layout(self) -> Response:
        """
        Replace the whole catalog layout (blocks + task order) -- `hashpass catalog layout`.

        Admin-only like the web drag-and-drop: it renumbers and can de-list any task. Refs that
        are not published on the pool are dropped by `Catalog.set_layout`; the reply lists the
        resulting catalog so the caller can show the numbering.
        """
        _user, err = self._auth_role(("admin",))
        if err is not None:
            if err == HTTPStatus.FORBIDDEN:
                return self._json(HTTPStatus.FORBIDDEN,
                                  {"error": "раскладку каталога меняет только администратор"})
            return self._empty(err)
        data = request.get_json(silent=True) or {}
        blocks = data.get("blocks") if isinstance(data, dict) else None
        if not isinstance(blocks, list) or not all(
                isinstance(b, dict) and isinstance(b.get("tasks"), list) for b in blocks):
            return self._empty(HTTPStatus.BAD_REQUEST)
        catalog = self.catalog()
        listed = {str(r) for b in blocks for r in b["tasks"]}
        owners = {_owner_of(r) for r in listed}
        # The layout governs the namespaces it mentions. Tasks of OTHER authors are not this
        # deploy's business: they keep their catalog place (own blocks, in order) after the
        # requested ones. Same-namespace tasks left out are de-listed -- and reported.
        current = catalog.blocks()
        foreign = [{"id": b.id, "name": b.name, "open": b.open,
                    "tasks": [e.ref for e in b.entries
                              if e.ref not in listed and _owner_of(e.ref.partition(":")[0]) not in owners]}
                   for b in current]
        foreign = [b for b in foreign if b["tasks"]]
        removed = [e.ref for b in current for e in b.entries
                   if e.ref not in listed and _owner_of(e.ref.partition(":")[0]) in owners]
        by_name = {b.name: b for b in current}
        layout = []
        for b in blocks:
            was = by_name.get(str(b.get("name", "")))
            entry = dict(b)
            entry["tasks"] = [str(r) for r in b["tasks"]]
            if was is not None:                    # keep the block's id and collapsed state
                entry.setdefault("id", was.id)
                entry.setdefault("open", was.open)
            layout.append(entry)
        requested = {str(e.get("name", "")): e for e in layout}
        for b in foreign:                          # same name = same block, never a twin id
            home = requested.get(b["name"])
            if home is not None:
                home["tasks"].extend(b["tasks"])
            else:
                layout.append(b)
        catalog.set_layout(layout)
        return self._json(HTTPStatus.OK, {"catalog": [e.as_dict() for e in catalog.entries()],
                                          "removed": removed})

    def _route_catalog_hidden(self) -> Response:
        """Hide or show one task (the hashpass TUI): an author its own tasks, an admin any."""
        user, err = self._auth_role(_AUTHOR_ROLES)
        if err is not None:
            return self._empty(err)
        data = request.get_json(silent=True) or {}
        ref = str(data.get("ref", "")) if isinstance(data, dict) else ""
        if not ref or not isinstance(data.get("hidden"), bool):
            return self._empty(HTTPStatus.BAD_REQUEST)
        name = ref.partition(":")[0]
        if not self._may_write(user, name):
            return self._json(HTTPStatus.FORBIDDEN, {"error": _ownership_message(name)})
        if not self.catalog().set_task_hidden(ref, hidden=data["hidden"]):
            return self._json(HTTPStatus.NOT_FOUND, {"error": f"в каталоге нет {ref}"})
        return self._json(HTTPStatus.OK, {"ref": ref, "hidden": data["hidden"]})

    def _route_catalog_block(self) -> Response:
        """Open or close a block for students (the hashpass TUI); an author or the admin, as on the web."""
        _user, err = self._auth_role(_AUTHOR_ROLES)
        if err is not None:
            return self._empty(err)
        data = request.get_json(silent=True) or {}
        block_id = str(data.get("block_id", "")) if isinstance(data, dict) else ""
        if not block_id or not isinstance(data.get("open"), bool):
            return self._empty(HTTPStatus.BAD_REQUEST)
        if not self.catalog().set_block_open(block_id, open_=data["open"]):
            return self._json(HTTPStatus.NOT_FOUND, {"error": "такого блока нет в каталоге"})
        return self._json(HTTPStatus.OK, {"block_id": block_id, "open": data["open"]})

    def _route_catalog_move(self) -> Response:
        """Move one task a step up/down (the hashpass TUI); admin-only like web drag-and-drop."""
        _user, err = self._auth_role(("admin",))
        if err is not None:
            if err == HTTPStatus.FORBIDDEN:
                return self._json(HTTPStatus.FORBIDDEN,
                                  {"error": "порядок заданий меняет только администратор"})
            return self._empty(err)
        data = request.get_json(silent=True) or {}
        ref = str(data.get("ref", "")) if isinstance(data, dict) else ""
        step = data.get("step") if isinstance(data, dict) else None
        if not ref or step not in (-1, 1):
            return self._empty(HTTPStatus.BAD_REQUEST)
        moved = self.catalog().move_task(ref, step)
        return self._json(HTTPStatus.OK, {"ref": ref, "moved": moved})

    def _route_submit(self) -> Response:   # noqa: PLR0911, C901
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return self._empty(HTTPStatus.BAD_REQUEST)
        task_ref = str(data.get("task_ref", ""))
        digest = str(data.get("digest", ""))
        passed = bool(data.get("passed", False))
        history = _sanitize_history(data.get("history"))
        authenticity = _sanitize_authenticity(data.get("authenticity"))
        if not data.get("course") and self.default_course() is not None:
            data = data | {"course": self.config.default_course}
        if data.get("course"):
            return self._course_submit(user, data, task_ref, digest, passed, history, authenticity)
        entry = self.catalog().find(task_ref)
        if entry is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        if not entry.available:
            return self._json(HTTPStatus.OK, {"status": "unavailable"})
        prog = self.progress()
        if self._credited(user, task_ref):
            # credited once -- final: a re-run neither rewrites the record nor adds a solution
            return self._json(HTTPStatus.OK, {"status": "passed",
                                              "global_key": global_key(self.secret, user, task_ref)})
        if digest not in (entry.digest, entry.approved_digest):
            prog.record(user, task_ref, status="failed", ts=_now(), digest=digest,
                        history=history, authenticity=authenticity)
            return self._json(HTTPStatus.OK, {"status": "failed", "reason": "digest-mismatch"})
        if not passed:
            prog.record(user, task_ref, status="failed", ts=_now(), digest=digest,
                        history=history, authenticity=authenticity)
            return self._json(HTTPStatus.OK, {"status": "failed"})
        session_id = str(data.get("session_id", ""))
        if session_id:
            with contextlib.suppress(ValueError):          # a bad id just leaves no solution
                self.attempts().finish(user, task_ref, session_id, "passed")
        gkey = global_key(self.secret, user, task_ref)   # bound to the authenticated principal
        prog.record(user, task_ref, status="passed", ts=_now(), global_key=gkey, digest=digest,
                    history=history, authenticity=authenticity)
        return self._json(HTTPStatus.OK, {"status": "passed", "global_key": gkey})

    def _course_submit(self, user: str, data: dict, task_ref: str, digest: str,  # noqa: PLR0913, PLR0917
                       passed: bool, history: list | None, authenticity: dict | None) -> Response:  # noqa: FBT001
        """Credit a task solved in a course (spec §8): the course's revision, recorded with it."""
        repo, _, tag = task_ref.partition(":")
        course = self.course_api.courses.get(str(data["course"]))
        if course is None or course.find_task(repo, tag) is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        hit = self._course_revision(user, repo, tag, None, course.ref)
        if hit is None:
            return self._json(HTTPStatus.OK, {"status": "unavailable"})
        n = hit[1]
        rev = self.repo(repo).get(tag, n)
        self.course_api.enrollments.enroll(user, course.id)
        extra = {"course": course.ref, "n": n}
        if self._credited(user, task_ref):
            return self._json(HTTPStatus.OK, {"status": "passed",
                                              "global_key": global_key(self.secret, user, task_ref)})
        prog = self.progress()
        older = next((r.n for r in self.repo(repo).revisions(tag)
                      if r.n < n and digest and r.task_digest == digest), None)
        if older is not None:                     # a copy from before the course moved on: still a pass
            n, rev = older, self.repo(repo).get(tag, older)
            extra = {"course": course.ref, "n": n}
        if rev is None or digest != rev.task_digest:
            prog.record(user, task_ref, status="failed", ts=_now(), digest=digest, history=history,
                        authenticity=authenticity, extra=extra)
            return self._json(HTTPStatus.OK, {"status": "failed", "reason": "digest-mismatch"})
        if not passed:
            prog.record(user, task_ref, status="failed", ts=_now(), digest=digest, history=history,
                        authenticity=authenticity, extra=extra)
            return self._json(HTTPStatus.OK, {"status": "failed"})
        session_id = str(data.get("session_id", ""))
        if session_id:
            with contextlib.suppress(ValueError):
                self.attempts().finish(user, task_ref, session_id, "passed")
        gkey = global_key(self.secret, user, task_ref)
        prog.record(user, task_ref, status="passed", ts=_now(), global_key=gkey, digest=digest,
                    history=history, authenticity=authenticity, extra=extra)
        return self._json(HTTPStatus.OK, {"status": "passed", "global_key": gkey})

    def _route_attempt(self) -> Response:  # noqa: PLR0911
        """Append a console session's new commands (+ output); 409 says where to resume."""
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict) or not isinstance(data.get("seq"), int):
            return self._empty(HTTPStatus.BAD_REQUEST)
        task_ref = str(data.get("task_ref", ""))
        meta: dict[str, object] | None = None
        if not data.get("course") and self.default_course() is not None:
            data = data | {"course": self.config.default_course}
        if data.get("course"):
            course = self.course_api.courses.get(str(data["course"]))
            repo, _, tag = task_ref.partition(":")
            if course is None or course.find_task(repo, tag) is None or not can(
                    user, self.users.role(user), course, "play"):
                return self._empty(HTTPStatus.NOT_FOUND)
            self.course_api.enrollments.enroll(user, course.id)
            meta = {"course": course.ref}
        elif self.catalog().find(task_ref) is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        if self._credited(user, task_ref):
            # a re-run of a credited task is not kept (user, 2026-10-16): the first solution stays
            entries = data.get("entries") if isinstance(data.get("entries"), list) else []
            return self._json(HTTPStatus.OK, {"length": int(data["seq"]) + len(entries),
                                              "ignored": True})
        final = data.get("final")
        try:
            length = self.attempts().append(
                user, task_ref, str(data.get("session_id", "")), int(data["seq"]),
                data.get("entries") or [],
                final=str(final) if isinstance(final, str) and final != "passed" else None,
                meta=meta)
        except SeqMismatch as exc:
            return self._json(HTTPStatus.CONFLICT, {"length": exc.have})
        except ValueError:
            return self._empty(HTTPStatus.BAD_REQUEST)
        return self._json(HTTPStatus.OK, {"length": length})

    def _credited(self, user: str, ref: str) -> bool:
        """Whether the pool already credited `ref` to `user`."""
        rec = self.progress().get(user).get(ref)
        return isinstance(rec, dict) and rec.get("status") == "passed"

    def _route_solutions(self) -> Response:
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        return self._json(HTTPStatus.OK, {"solutions": self.attempts().solutions(user)})

    def _route_solution(self, ref: str) -> Response:
        """One saved solution: your own, or -- for an author/admin -- any student's (`?user=`)."""
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        target = request.args.get("user") or user
        if (target != user and self.users.role(user) not in _AUTHOR_ROLES
                and ref not in self._course_students(user).get(target, set())):
            return self._empty(HTTPStatus.FORBIDDEN)
        sol = self.attempts().solution(target, ref)
        if sol is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        return self._json(HTTPStatus.OK, sol)

    def _route_progress(self) -> Response:
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        store = self.progress()
        if self.users.role(user) in _AUTHOR_ROLES:     # admins (and legacy authors): everyone
            return self._json(HTTPStatus.OK, {"progress": store.all()})
        payload = {user: store.get(user)}
        for student, refs in self._course_students(user).items():
            mine = store.get(student)
            payload.setdefault(student, {}).update({r: v for r, v in mine.items() if r in refs})
        return self._json(HTTPStatus.OK, {"progress": payload})

    def _course_students(self, staff: str) -> dict[str, set[str]]:
        """Students who started a course `staff` authors or runs -> that course's task refs (spec §7)."""
        role = self.users.role(staff)
        out: dict[str, set[str]] = {}
        for course in self.course_api.courses.all():
            if not can(staff, role, course, "add"):
                continue
            refs = {f"{t['repo']}:{t['tag']}" for _b, t in course.tasks()}
            for student in self.course_api.enrollments.users_of(course.id):
                out.setdefault(student, set()).update(refs)
        return out

    def _pool_image_rows(self) -> list[dict[str, object]]:
        """One row per stored revision: its tag's catalog place, description, digest, newest-or-not."""
        entries = {e.ref: e for e in self.catalog().entries()}
        att = self.attachments()
        newest: dict[str, str] = {}
        rows: list[dict[str, object]] = []
        for ref in self.store.list():
            img = self.store.get(ref)
            name, _, version = ref.partition(":")
            tag, n, _latest = parse_version(version)
            is_task = (img.layer.parent / "task").exists()
            entry = entries.get(f"{name}:{tag}")
            info = att.describe(ref)
            newest.setdefault(f"{name}:{tag}", self.resolve(name, tag) or ref)
            rows.append({"ref": ref, "repo": name, "tag": tag, "n": n,
                         "kind": "task" if is_task else "image",
                         "number": entry.number if entry else None,
                         "block_id": entry.block_id if entry else None,
                         "block_name": entry.block_name if entry else "",
                         "available": entry.available if entry else None,
                         "description": info["description"], "files": info["files"],
                         "digest": img.digest})
        for row in rows:
            row["latest"] = newest.get(f"{row['repo']}:{row['tag']}") == row["ref"]
        return rows

    def _route_images(self) -> Response:
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        rows = [r for r in self._pool_image_rows() if self._may_see_repo(user, str(r["repo"]))]
        if self.users.role(user) not in _AUTHOR_ROLES:
            # a student: a catalogued tag only as its approved revision of an open task; other
            # tags only as plain images (bases) -- never a task outside the catalog
            entries = self.catalog().entries()
            catalogued = {e.ref for e in entries}
            served = {(r or "").removeprefix(_COPY) for e in entries if e.available
                      for r in (self._approved_rev(e),)}
            rows = [r for r in rows if r["ref"] in served
                    or (f"{r['repo']}:{r['tag']}" not in catalogued and r["kind"] != "task")]
        return self._json(HTTPStatus.OK, {"images": rows})

    # -- routes: blobs (image / task / closure / attachment) ----------------

    _UPLOAD_CHUNK = 1 << 20

    def _route_image_blob(self, tail: str) -> Response:
        parts = self._split_ref(tail)
        if parts is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        name, version = parts
        if request.method == "PUT":
            user, err = self._authorize_write(name, version)
            if err is not None:
                return err
            st, err = self._staging_for(user, name, version)
            if err is not None:
                return err
            resp = self._receive_image(name, version, st.images)
            if resp.status_code != HTTPStatus.CREATED or request.args.get("staging"):
                return resp
            return self._legacy_commit(user, name, version, st)   # an old client: commit at once
        return self._serve_image_for(name, version)

    def _serve_image_for(self, name: str, version: str) -> Response:
        """HEAD/GET an image: the revision this caller gets (`_view_revision`), named in `X-Image-Ref`."""
        ref = f"{name}:{version}"
        served = self._view_revision(self._token_user(), name, version)
        if served is None:
            return self._not_found_head(ref) if request.method == "HEAD" else self._not_found(ref)
        if served.startswith(_COPY):
            return self._serve_copy_blob(served.removeprefix(_COPY))
        if request.method == "HEAD":
            img = self.store.get(served)
            resp = self._empty(HTTPStatus.OK)
            if img.digest:
                resp.headers["X-Image-Digest"] = img.digest
        else:
            resp = self._serve_image_blob(served)
        resp.headers["X-Image-Ref"] = served
        return resp

    def _serve_copy_blob(self, ref: str) -> Response:
        """HEAD/GET the approved copy of a not-yet-moved ref (an update waits for approval)."""
        copies = ApprovedStore(Path(self.store.root) / "approved")
        path, digest = copies.blob(ref), copies.digest(ref)
        if path is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        if request.method == "HEAD":
            resp = self._empty(HTTPStatus.OK)
        else:
            f = path.open("rb")
            size = os.fstat(f.fileno()).st_size
            resp = send_file(f, mimetype="application/octet-stream", conditional=False)
            resp.content_length = size
        if digest:
            resp.headers["X-Image-Digest"] = digest
        resp.headers["X-Image-Ref"] = ref
        return resp

    def _serve_image_blob(self, ref: str) -> Response:
        """
        GET an image blob: ONE meta read gives both the digest and the file.

        The file is opened before answering, so a publish racing this request can unlink it
        only after we hold the fd -- the body always matches the `X-Image-Digest` sent with it.
        """
        try:
            img = self.store.get(ref)
        except KeyError:
            return self._not_found(ref)
        if not img.blob:                      # legacy record (layer/ only): pack on the fly
            return self._blob(HTTPStatus.OK, pack_image(img))
        path = self.store.blob_path_of(img)
        try:
            f = path.open("rb") if path is not None else None
        except FileNotFoundError:
            f = None
        if f is None:                         # meta names a blob that is not (or no longer) there
            return self._empty(HTTPStatus.NOT_FOUND)
        size = os.fstat(f.fileno()).st_size
        resp = send_file(f, mimetype="application/octet-stream", conditional=False)
        resp.content_length = size
        if img.digest:
            resp.headers["X-Image-Digest"] = img.digest
        return resp

    def _receive_image(self, name: str, version: str, store: ImageStore) -> Response:
        """
        Stream an uploaded image blob to disk, validate it, publish it as the new generation.

        The blob is kept verbatim (never unpacked here) so the digest names exactly the bytes
        later GETs serve, and root-owned members keep their ownership for the client's
        `sudo tar`. A malformed archive is refused with 400 and the previous generation
        stays published untouched.
        """
        try:
            store.dir(name, version)                      # validates name/version only
        except ValueError:
            return self._empty(HTTPStatus.BAD_REQUEST)
        # Stream into the store root's `.incoming/`, not the image dir: a rejected PUT to a
        # new ref must not leave an empty `<name>/<ver>/` behind. publish_blob creates the
        # image dir and moves the file in (same filesystem, so a plain rename).
        incoming = Path(self.store.root) / ".incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        tmp = incoming / f"{uuid.uuid4().hex}.tmp"
        digest = hashlib.sha256()
        # `finally` guarantees the temp file is swept on EVERY failure path, not just the
        # ones we recognize below -- e.g. a client that declares a Content-Length and then
        # stops sending data trips werkzeug's ClientDisconnected (an HTTPException, not an
        # OSError), which would otherwise slip past the `except` and leak `incoming-*.tmp`
        # forever. On success `publish_blob` has already moved `tmp` to its final blob path,
        # so the unlink below is a harmless no-op (missing_ok=True).
        try:
            with tmp.open("wb") as out:
                while chunk := request.stream.read(self._UPLOAD_CHUNK):
                    digest.update(chunk)
                    out.write(chunk)
            info = inspect_image_blob(tmp)
            _check_image_ref(info, name, version)
            img = store.publish_blob(name, version, tmp, parents=info.parents,
                                     digest=digest.hexdigest())
        except (ValueError, OSError, tarfile.TarError):
            return self._empty(HTTPStatus.BAD_REQUEST)
        finally:
            tmp.unlink(missing_ok=True)
        resp = self._empty(HTTPStatus.CREATED)
        if img.digest:
            resp.headers["X-Image-Digest"] = img.digest
        return resp

    def _route_task_blob(self, tail: str) -> Response:
        parts = self._split_ref(tail)
        if parts is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        name, version = parts
        if request.method == "DELETE":
            return self._task_delete(name, version)
        if request.method == "PUT":
            return self._task_put(name, version)
        return self._task_get(name, version)

    def _task_delete(self, name: str, version: str) -> Response:
        """Remove a task from the pool: its author (namespace owner) or an admin."""
        ref = f"{name}:{version}"
        _user, err = self._authorize_write(name, version)
        if err is not None:
            return err
        revisions = self._tag_revisions(ref)
        if not revisions and self.catalog().find(ref) is None:
            return self._not_found(ref)
        dependents = [r for r in self.store.list() if r not in revisions
                      and ({*self.store.get(r).parents, self.store.get(r).base} & {*revisions, ref})]
        if dependents:
            return self._json(HTTPStatus.CONFLICT, {
                "error": f"на {ref} строятся другие образы: {', '.join(dependents)} — сначала их"})
        self._delete_task(ref)
        return self._empty(HTTPStatus.OK)

    def _task_put(self, name: str, version: str) -> Response:
        """`push --task [--block B]`: the task's grader into the staging area (+ publish intent)."""
        user, err = self._authorize_write(name, version)
        if err is not None:
            return err
        st, err = self._staging_for(user, name, version)
        if err is not None:
            return err
        try:
            task_dir = st.images.dir(name, version) / "task"
            unpack_task(request.get_data(cache=False, as_text=False), task_dir)
        except (ValueError, OSError, tarfile.TarError):
            return self._empty(HTTPStatus.BAD_REQUEST)
        if request.args.get("publish", "") == "1":
            st.save_intent(st.intent | {"publish": True, "block": request.args.get("block") or ""})
        if request.args.get("staging"):
            return self._empty(HTTPStatus.CREATED)
        resp = self._legacy_commit(user, name, version, st)
        return self._empty(HTTPStatus.CREATED) if resp.status_code < HTTPStatus.BAD_REQUEST else resp

    def _task_get(self, name: str, version: str) -> Response:
        """Send a task's grader (never public) of the revision this caller gets."""
        ref = f"{name}:{version}"
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        served = self._view_revision(user, name, version)
        if served is None:
            return self._not_found(ref)
        if served.startswith(_COPY):
            copy_task = ApprovedStore(Path(self.store.root) / "approved").task_dir(ref)
            if copy_task is None:
                return self._empty(HTTPStatus.NOT_FOUND)
            return self._blob(HTTPStatus.OK, pack_task(copy_task))
        task_dir = self.store.get(served).layer.parent / "task"
        if not task_dir.exists():
            return self._empty(HTTPStatus.NOT_FOUND)
        resp = self._blob(HTTPStatus.OK, pack_task(task_dir))
        resp.headers["X-Image-Ref"] = served
        return resp

    # -- revisions: staging, commit (spec 2026-10-21 §2.3) -----------------

    def _staging_for(self, user: str, name: str, tag: str) -> tuple[Staging | None, Response | None]:
        """Open the staging area named by `?staging=` (checked against user + ref); an old client gets a fresh one."""
        sid = request.args.get("staging", "")
        if not sid:
            try:
                check_tag(tag)
            except ValueError as exc:
                return None, self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return new_staging(self.store.root, owner=user, name=name, tag=tag), None
        try:
            st = Staging(self.store.root, sid)
        except ValueError:
            return None, self._empty(HTTPStatus.BAD_REQUEST)
        intent = st.intent
        if not st.exists() or (intent.get("name"), intent.get("tag")) != (name, tag):
            return None, self._json(HTTPStatus.NOT_FOUND, {"error": "черновик отправки не найден — начните push заново"})
        if intent.get("owner") != user and self.users.role(user) != "admin":
            return None, self._empty(HTTPStatus.FORBIDDEN)
        return st, None

    def _ref_target(self, user: str, name: str, version: str, kind: str) -> tuple[object | None, str]:
        """
        Pick where an attachment/source PUT lands.

        The staging area (`?staging=`) or, for an old client, the tag's newest revision (it
        already committed on PUT image/task).
        """
        if request.args.get("staging"):
            st, err = self._staging_for(user, name, version)
            if err is not None or st is None:
                return None, ""
            return getattr(st, kind), f"{name}:{version}"
        ref = self.resolve(name, version)
        if ref is None:
            return None, ""
        return (self.attachments() if kind == "attachments" else self.sources()), ref

    def _route_revisions(self, tail: str) -> Response:  # noqa: PLR0911
        """
        Revisions API (spec 2026-10-21 §2).

        GET name -> tags + revisions; POST name/tag -> open a staging area; POST name/tag/commit;
        POST name/tag/tag {from, to}; POST name/fork {from}; DELETE name/tag/N.
        """
        if "/merges" in tail:
            target, _, rest = tail.partition("/merges")
            return self._route_merges(target, rest.strip("/"))
        if request.method == "GET":
            return self._revisions_get(tail)
        if request.method == "PUT":
            return self._repo_settings(tail)
        if request.method == "DELETE":
            return self._revision_delete(tail)
        for suffix, handler in (("/commit", self._revision_commit), ("/tag", self._revision_tag)):
            if tail.endswith(suffix):
                return handler(tail.removesuffix(suffix))
        if tail.endswith("/fork"):
            return self._revision_fork(tail.removesuffix("/fork"))
        return self._revision_begin(tail)

    def _write_tag(self, tail: str) -> tuple[str, str, str, Response | None]:
        """Parse `name/tag` of a write; check ownership and the tag itself."""
        parts = self._split_ref(tail)
        if parts is None:
            return "", "", "", self._empty(HTTPStatus.NOT_FOUND)
        name, tag = parts
        user, err = self._authorize_write(name, tag)
        if err is not None:
            return "", "", "", err
        try:
            check_tag(tag)
            self.store.dir(name, tag)
        except ValueError as exc:
            return "", "", "", self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        return user, name, tag, None

    def _revision_begin(self, tail: str) -> Response:
        data = request.get_json(silent=True) or {}
        data = data if isinstance(data, dict) else {}
        proposal = self._proposal_target(tail) if data.get("propose") else None
        if isinstance(proposal, Response):
            return proposal
        if proposal is not None:                       # no right to publish: into one's fork
            target, tail = proposal
        user, name, tag, err = self._write_tag(tail)
        if err is not None:
            return err
        sweep_stale(self.store.root)
        st = new_staging(self.store.root, owner=user, name=name, tag=tag)
        base = str(data.get("base", ""))
        if base:                                       # the base it was built on (an implicit FROM)
            st.save_intent(st.intent | {"base": base})
        if proposal is not None:
            st.save_intent(st.intent | {"propose_to": target})
            return self._json(HTTPStatus.CREATED, {"staging": st.sid, "name": name, "proposal_to": target})
        return self._json(HTTPStatus.CREATED, {"staging": st.sid, "name": name})

    def _proposal_target(self, tail: str) -> tuple[str, str] | Response | None:
        """
        Tell where a push without the right to publish goes (spec 2026-10-23 §3).

        A new client asks with `propose`: if the caller sees `name` but may not publish it, the
        push goes into their fork `<them>/<name>` (made now if missing), and committing it
        opens a proposal. Returns (target, the fork's `name/tag`), None (they may publish --
        a plain push), or an error.
        """
        parts = self._split_ref(tail)
        user = self._token_user()
        if parts is None or user is None:
            return None
        name, tag = parts
        if not self.repo(name).exists or self._may_write(user, name) or not self._may_see_repo(user, name):
            return None
        fork = f"{user}/{name.split('/', 1)[1]}"
        with self.repo(fork).locked() as idx:
            if not idx.exists:
                idx.set_meta(fork_of=f"{name}:{tag}")
            elif not idx.fork_of.startswith(f"{name}:"):
                return self._json(HTTPStatus.CONFLICT, {
                    "error": f"у вас уже есть свой {fork}, не форк {name} — предложите через форк с другим "
                             f"именем: hashpass fork {name}:{tag} <имя>"})
        return name, f"{fork}/{tag}"

    def _revision_commit(self, tail: str) -> Response:
        user, name, tag, err = self._write_tag(tail)
        if err is not None:
            return err
        data = request.get_json(silent=True) or {}
        sid = str(data.get("staging", "")) if isinstance(data, dict) else ""
        try:
            st = Staging(self.store.root, sid)
        except ValueError:
            return self._empty(HTTPStatus.BAD_REQUEST)
        intent = st.intent
        if not st.exists() or (intent.get("name"), intent.get("tag")) != (name, tag):
            return self._json(HTTPStatus.NOT_FOUND, {"error": "черновик отправки не найден — начните push заново"})
        if intent.get("owner") != user and self.users.role(user) != "admin":
            return self._empty(HTTPStatus.FORBIDDEN)
        message = str(data.get("message", "")).strip()[:_MAX_MESSAGE] if isinstance(data, dict) else ""
        target = str(intent.get("propose_to") or "")
        resp = self._commit(user, name, tag, st, message=message)
        if not target or resp.status_code not in (HTTPStatus.OK, HTTPStatus.CREATED):
            return resp
        body = resp.get_json() or {}                   # the fork's version -> a proposal to the owner
        row = self.merges(target).offer(src=str(body["ref"]), to_tag=tag, by=user, comment=message)
        return self._json(HTTPStatus(resp.status_code), body | {"proposal": {"to": target, "id": row["id"]}})

    def _revisions_get(self, name: str) -> Response:
        if self._token_user() is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        try:
            self.store.dir(name, "x")                 # validates the name
        except ValueError:
            return self._empty(HTTPStatus.BAD_REQUEST)
        idx = self.repo(name)
        if not idx.exists or not self._may_see_repo(self._token_user(), name):
            return self._not_found(name)
        return self._json(HTTPStatus.OK, idx.as_dict())

    def _may_see_repo(self, user: str | None, name: str) -> bool:
        """Tell whether `user` sees repository `name`: public -- anyone; private -- owner and admins."""
        return self.repo(name).visibility == "public" or self._repo_level(user, name) >= 0

    def _may_read_sources(self, user: str | None, name: str, filename: str = "") -> bool:
        """
        Whether `user` may read a task's sources (spec §2.6).

        README/about.md: whoever sees the image; the rest: signed in and the repository not
        hiding its service files -- else only its owner and admins.
        """
        if user is None or not self._may_see_repo(user, name):
            return False
        if filename.rsplit("/", 1)[-1] in ("README.md", "about.md"):
            return True
        return not self.repo(name).hide_sources or self._may_write(user, name)

    def _web_compare(self, name: str) -> Response:
        """
        Compare two versions of an image, like GitHub (spec 2026-10-23 §3).

        `?from=&to=` -- a version of this image (`1_v2`, a tag = its newest) or a full ref of
        another one (a proposal's fork version). Files added / removed / changed, with diffs.
        """
        viewer = self._session_user()
        if viewer is None:
            return self._redirect(f"/web/login?next={quote(request.full_path, safe='')}")
        refs = []
        for key in ("from", "to"):
            raw = request.args.get(key, "")
            other, sep, version = raw.rpartition(":")
            repo_name, ver = (other, version) if sep else (name, raw)
            resolved = self.resolve(repo_name, ver) if repo_name and ver else None
            if resolved is None or not self._may_read_sources(viewer, repo_name):
                return self._web_not_found(f"{repo_name}:{ver}")
            refs.append(resolved)
        trees = [self.sources()._dir(r) if self._sources_ready(r)                      # noqa: SLF001
                 else self.store.get(r).layer.parent / "task" for r in refs]   # older pushes: task/
        files = tree_diff(trees[0], trees[1])
        return self._html(render_compare(name, refs[0], refs[1], files))

    def _route_repo_members(self, tail: str) -> Response:  # noqa: PLR0911
        """
        Set or take a role in an image: PUT/DELETE /repo-members/<owner>/<name>/<login> {role}.

        Spec 2026-10-23 §2: the owner gives member / author / maintainer, or takes it away.
        """
        name, _, login = tail.rpartition("/")
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        if not name or not self.repo(name).exists or not self._may_see_repo(user, name):
            return self._not_found(name or tail)
        if self._repo_level(user, name) < OWNER:
            return self._empty(HTTPStatus.FORBIDDEN)
        if not self.users.has(login):
            return self._json(HTTPStatus.NOT_FOUND, {"error": f"нет пользователя {login}"})
        if login == _owner_of(name):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "это владелец образа"})
        role = None
        if request.method == "PUT":
            data = request.get_json(silent=True) or {}
            role = str(data.get("role", "")) if isinstance(data, dict) else ""
        try:
            with self.repo(name).locked() as idx:
                idx.set_member(login, role)
                members = idx.members
        except ValueError as exc:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        return self._json(HTTPStatus.OK, {"members": members})

    def _repo_settings(self, name: str) -> Response:
        """PUT name {visibility?, hide_sources?}: the owner's repository settings (spec §2.5, §2.6)."""
        user, err = self._authorize_write(name, "x")
        if err is not None:
            return err
        if self._repo_level(user, name) < OWNER:                  # spec 2026-10-23 §2: the owner only
            return self._empty(HTTPStatus.FORBIDDEN)
        if not self.repo(name).exists:
            return self._not_found(name)
        data = request.get_json(silent=True) or {}
        visibility = data.get("visibility")
        if visibility == "private":
            blockers = [c.ref for c in self.course_api.courses.all() if c.visibility == "public"
                        and any(t["repo"] == name for _b, t in c.tasks())]
            blockers += sorted({r for r in self.store.list()
                                if r.partition(":")[0] != name and self.repo(r.partition(":")[0]).visibility == "public"
                                and any(p.partition(":")[0] == name
                                        for p in (*self.store.get(r).parents, self.store.get(r).base or ""))})
            if blockers:
                return self._json(HTTPStatus.CONFLICT, {
                    "error": f"{name} нельзя сделать приватным: его используют {', '.join(blockers)}",
                    "blockers": blockers})
        try:
            with self.repo(name).locked() as idx:
                fields = {k: data[k] for k in ("visibility", "hide_sources") if k in data}
                if "hide_sources" in fields:
                    fields["hide_sources"] = bool(fields["hide_sources"])
                idx.set_meta(**fields)
        except ValueError as exc:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        return self._json(HTTPStatus.OK, self.repo(name).as_dict())

    def _copy_revision(self, src_ref: str, name: str, tag: str, by: str,  # noqa: PLR0913
                       idx: RepoIndex, *, merged_from: str = "", message: str = "",
                       accepted_by: str = "") -> str:
        """Add revision `name:tag_vN` with `src_ref`'s content (shared blob) + files; `idx` is locked."""
        src_name, _, src_version = src_ref.partition(":")
        src_tag, src_n, _ = parse_version(src_version)
        src_rev = self.repo(src_name).get(src_tag, src_n) if src_n is not None else None
        img = self.store.get(src_ref)
        n = idx.peek_next(tag)
        ref = f"{name}:{revision_version(tag, n)}"
        made: list[Path] = []
        try:
            made.append(self.store.dir(name, revision_version(tag, n)))
            self.store.link_revision(src_ref, name, revision_version(tag, n), parents=img.parents)
            if img.base:                                # the base it stands on comes along
                self._set_meta_field(made[0], "base", img.base)
            for live in (self.attachments(), self.sources()):
                src_dir, out = live._dir(src_ref), live._dir(ref)            # noqa: SLF001
                if src_dir.is_dir():
                    made.append(out)
                    shutil.copytree(src_dir, out, symlinks=True)
            task = img.layer.parent / "task"
            idx.add(tag, {"image_digest": img.digest or "",
                          "task_digest": src_rev.task_digest if src_rev else (
                              task_digest(task) if task.is_dir() else ""),
                          "parents": list(img.parents), "by": by, "merged_from": merged_from,
                          "message": message, "accepted_by": accepted_by})
        except BaseException:
            for d in made:
                shutil.rmtree(d, ignore_errors=True)
            raise
        return ref

    def _revision_tag(self, tail: str) -> Response:  # noqa: PLR0911
        """Tag one of your revisions: a new revision of tag `to` with the same content."""
        parts = self._split_ref(tail)                 # name/<the source's version>
        if parts is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        name = parts[0]
        user, err = self._authorize_write(name, parts[1])
        if err is not None:
            return err
        if self._repo_level(user, name) < MAINTAINER:                  # tags: a maintainer and up
            return self._empty(HTTPStatus.FORBIDDEN)
        data = request.get_json(silent=True) or {}
        src, to = str(data.get("from", "")), str(data.get("to", ""))
        src_name, _, src_version = src.partition(":")
        if src_name != name:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "навесить тег можно только внутри репозитория"})
        try:
            check_tag(to)
            self.store.dir(name, to)
        except ValueError as exc:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        resolved = self.resolve(src_name, src_version or "latest")
        if resolved is None or not parse_version(resolved.partition(":")[2])[1]:
            return self._not_found(src)
        with self.repo(name).locked() as idx:
            try:
                ref = self._copy_revision(resolved, name, to, user, idx)
            except (OSError, ValueError, KeyError) as exc:
                return self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"тег не навешен: {exc}"})
        return self._json(HTTPStatus.CREATED, {"ref": ref, "n": parse_version(ref.partition(":")[2])[1]})

    def _revision_fork(self, name: str) -> Response:
        """Fork a revision you can see into your namespace (spec §2.8): `name` must be yours and new."""
        user, err = self._authorize_write(name, "x")
        if err is not None:
            return err
        data = request.get_json(silent=True) or {}
        src = str(data.get("from", ""))
        src_name, _, src_version = src.partition(":")
        resolved = self.resolve(src_name, src_version or "latest") if src_name else None
        if (resolved is None or not parse_version(resolved.partition(":")[2])[1]
                or (self.repo(src_name).visibility != "public" and not self._may_write(user, src_name))):
            return self._not_found(src or name)
        idx = self.repo(name)
        if idx.exists or any(r.partition(":")[0] == name for r in self.store.list()):
            return self._json(HTTPStatus.CONFLICT, {"error": f"репозиторий {name} уже есть — выберите другое имя"})
        tag = parse_version(resolved.partition(":")[2])[0]
        with idx.locked() as w:
            try:
                ref = self._copy_revision(resolved, name, tag, user, w)
            except (OSError, ValueError, KeyError) as exc:
                return self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"форк не создан: {exc}"})
            w.set_meta(fork_of=resolved, visibility=self.repo(src_name).visibility)
        return self._json(HTTPStatus.CREATED, {"ref": ref, "n": 1})

    def _revision_delete(self, tail: str) -> Response:  # noqa: PLR0911
        """
        Remove one revision (§2.7).

        Refused while other images stand on it (`from`, base). Used by someone else's course ->
        a request the admin decides (the owner may withdraw it); the admin deletes at once.
        """
        head, _, n_raw = tail.rpartition("/")
        parts = self._split_ref(head)
        if parts is None or not n_raw.isdigit():
            return self._empty(HTTPStatus.NOT_FOUND)
        name, tag = parts
        user, err = self._authorize_write(name, tag)
        if err is not None:
            return err
        if self._repo_level(user, name) < MAINTAINER:                  # deleting versions: a maintainer and up
            return self._empty(HTTPStatus.FORBIDDEN)
        n = int(n_raw)
        ref = f"{name}:{revision_version(tag, n)}"
        if self.repo(name).get(tag, n) is None:
            return self._not_found(ref)
        dependents = self._dependents(ref)
        if dependents:
            return self._json(HTTPStatus.CONFLICT, {
                "error": f"на {ref} строятся другие образы: {', '.join(dependents)} — сначала их",
                "dependents": dependents})
        foreign = self._foreign_courses(name, tag, n)
        if foreign and self.users.role(user) != "admin":
            req = self.deletions().open(ref, by=user, courses=[c.ref for c in foreign])
            return self._json(HTTPStatus.ACCEPTED, {
                "request": req["id"], "courses": self._course_names(foreign, user),
                "message": "версия стоит в чужих курсах — удаление ждёт решения администратора"})
        self._delete_revision(name, tag, n)
        return self._json(HTTPStatus.OK, {"removed": ref})

    def merges(self, name: str) -> MergeRequests:
        return MergeRequests(Path(self.store.root) / ".repos" / name)

    def _route_merges(self, target: str, rest: str) -> Response:  # noqa: PLR0911, C901
        """
        Merge requests into `target` (spec §2.8).

        GET -> the list (owner/admin: all; others: their own); GET <id>/diff -> the source diff;
        POST {from, to_tag, comment} -> offer a fork revision; POST <id> {action: merge|reject|withdraw}.
        """
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        try:
            self.store.dir(target, "x")
        except ValueError:
            return self._empty(HTTPStatus.BAD_REQUEST)
        if not self.repo(target).exists or not self._may_see_repo(user, target):
            return self._not_found(target)
        owner = self._repo_level(user, target) >= MAINTAINER          # decide proposals: a maintainer and up
        store = self.merges(target)
        if request.method == "GET":
            mid, _, what = rest.partition("/")
            if mid and what == "diff":
                return self._merge_diff(target, store.get(mid), user, owner=owner)
            rows = [r for r in store.all() if owner or r["by"] == user]
            return self._json(HTTPStatus.OK, {"merges": rows})
        data = request.get_json(silent=True) or {}
        if not rest:
            return self._merge_offer(target, user, data)
        row = store.get(rest)
        if row is None or row["state"] != "open":
            return self._json(HTTPStatus.NOT_FOUND, {"error": "такого открытого запроса нет"})
        action = str(data.get("action", ""))
        if action == "withdraw":
            if row["by"] != user:
                return self._empty(HTTPStatus.FORBIDDEN)
            return self._json(HTTPStatus.OK, store.close(rest, "withdrawn", by=user))
        if action not in ("merge", "reject") or not owner:
            return self._empty(HTTPStatus.FORBIDDEN)
        if action == "reject":
            return self._json(HTTPStatus.OK, store.close(rest, "rejected", by=user,
                                                         reason=str(data.get("reason", ""))))
        if not self.store.exists(row["from"]):
            return self._json(HTTPStatus.CONFLICT, {"error": f"версии {row['from']} больше нет"})
        with self.repo(target).locked() as idx:      # its author: who proposed; spec 2026-10-23 §3
            ref = self._copy_revision(row["from"], target, row["to_tag"], str(row.get("by") or user), idx,
                                      merged_from=row["from"], message=str(row.get("comment", "")),
                                      accepted_by=user)
        return self._json(HTTPStatus.OK, store.close(rest, "merged", by=user, result=ref))

    def _merge_offer(self, target: str, user: str, data: dict) -> Response:
        src = str(data.get("from", ""))
        src_name, _, src_version = src.partition(":")
        to_tag = str(data.get("to_tag", "")) or parse_version(src_version)[0]
        try:
            check_tag(to_tag)
        except ValueError as exc:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        if not src_name or not self._may_write(user, src_name):
            return self._empty(HTTPStatus.FORBIDDEN)
        if not self.repo(src_name).fork_of.startswith(f"{target}:"):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": f"{src_name} — не форк {target}"})
        resolved = self.resolve(src_name, src_version or "latest")
        if resolved is None or parse_version(resolved.partition(":")[2])[1] is None:
            return self._not_found(src)
        row = self.merges(target).offer(src=resolved, to_tag=to_tag, by=user,
                                        comment=str(data.get("comment", "")))
        return self._json(HTTPStatus.CREATED, row)

    def _merge_diff(self, target: str, row: dict | None, user: str, *, owner: bool) -> Response:
        if row is None or not (owner or row["by"] == user):
            return self._json(HTTPStatus.NOT_FOUND, {"error": "такого запроса нет"})
        base = self.resolve(target, row["to_tag"])
        old = self.sources()._dir(base) if base else None             # noqa: SLF001
        new = self.sources()._dir(row["from"])                        # noqa: SLF001
        return self._json(HTTPStatus.OK, {"from": row["from"], "to": base or f"{target}:{row['to_tag']}",
                                          "files": tree_diff(old, new)})

    def _route_deletions(self) -> Response:
        """List open deletion requests: all for the admin, their own for an owner."""
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        rows = [r for r in self.deletions().all() if r["state"] == "open"
                and (self.users.role(user) == "admin" or r["by"] == user)]
        return self._json(HTTPStatus.OK, {"requests": rows})

    def _route_deletion(self, rid: str) -> Response:
        """POST {action: approve|reject} (admin) or {action: withdraw} (its owner)."""
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        action = str((request.get_json(silent=True) or {}).get("action", ""))
        row = next((r for r in self.deletions().all() if r["id"] == rid and r["state"] == "open"), None)
        if row is None:
            return self._json(HTTPStatus.NOT_FOUND, {"error": "такого открытого запроса нет"})
        admin = self.users.role(user) == "admin"
        if (action == "withdraw" and row["by"] != user) or (action in ("approve", "reject") and not admin) \
                or action not in ("approve", "reject", "withdraw"):
            return self._empty(HTTPStatus.FORBIDDEN)
        if action == "approve":
            name, _, version = row["ref"].partition(":")
            tag, n, _latest = parse_version(version)
            if n is not None and self.repo(name).get(tag, n) is not None:
                if self._dependents(row["ref"]):
                    return self._json(HTTPStatus.CONFLICT, {"error": "на этой версии уже строятся другие образы"})
                self._delete_revision(name, tag, n)
        state = {"approve": "approved", "reject": "rejected", "withdraw": "withdrawn"}[action]
        self.deletions().set_state(rid, state, user)
        return self._json(HTTPStatus.OK, {"id": rid, "state": state})

    def _dependents(self, ref: str) -> list[str]:
        return sorted(r for r in self.store.list() if r != ref and (
            ref in self.store.get(r).parents or self.store.get(r).base == ref))

    def _foreign_courses(self, name: str, tag: str, n: int) -> list["course_model.Course"]:
        """Courses of someone other than the repository's owner showing revision n of name:tag."""
        owner = _owner_of(name)
        latest = self.repo(name).latest(tag)
        return [c for c in self.course_api.courses.courses_with(name, tag) if c.owner != owner
                and course_model.effective_n(c, c.find_task(name, tag),
                                             latest=latest.n if latest else None) == n]

    def _course_names(self, found: list["course_model.Course"], user: str) -> list[str]:
        """Course names for `user`: private courses they are not in stay unnamed."""
        role = self.users.role(user)
        named = [c.ref for c in found if can(user, role, c, "view")]
        hidden = len(found) - len(named)
        return named + ([f"ещё приватных курсов: {hidden}"] if hidden else [])

    def deletions(self) -> "DeletionRequests":
        return DeletionRequests(Path(self.store.root) / ".deletion-requests.json")

    def _delete_revision(self, name: str, tag: str, n: int) -> None:
        """Delete revision n and settle every course that showed it (spec §2.7)."""
        ref = f"{name}:{revision_version(tag, n)}"
        with self.repo(name).locked() as idx:
            idx.remove(tag, n)
            remaining = [r.n for r in idx.revisions(tag) if r.n < n]
            newest = idx.latest(tag)
        self.sources().remove(ref)
        with contextlib.suppress(ValueError, OSError):
            shutil.rmtree(self.attachments().ref_path(ref), ignore_errors=True)
        with contextlib.suppress(ValueError, OSError):
            shutil.rmtree(self.store.dir(name, revision_version(tag, n)), ignore_errors=True)
        for course in self.course_api.courses.courses_with(name, tag):
            self._settle_course(course.ref, name, tag, n, remaining, newest.n if newest else None)

    def _settle_course(self, course_ref: str, name: str, tag: str, n: int,  # noqa: PLR0913, PLR0917
                       remaining: list[int], newest: int | None) -> None:
        """Settle one course: following the newest -> falls back; pinned to n -> task removed + `restore`."""
        with self.course_api.courses.edit(course_ref) as course:
            task = course.find_task(name, tag)
            if task is None or int(task["n"]) != n:
                if task is not None and newest is None:
                    course_model.remove_task(course, name, tag)
                return
            following = course.auto_update and not task.get("pinned")
            if following and newest is not None:
                task["n"] = newest
                return
            block_id = next(b["id"] for b, t in course.tasks() if t is task)
            course_model.remove_task(course, name, tag)
            if remaining:
                course_model.propose(course, "restore", name, tag, max(remaining), block_id,
                                     by=_owner_of(name) or "", now=time.time(),
                                     comment=f"версия {n} удалена владельцем — вернуть версию {max(remaining)}?")

    def _legacy_commit(self, user: str, name: str, tag: str, st: Staging) -> Response:
        """Commit an old client's PUT (no staging) as a revision right away."""
        resp = self._commit(user, name, tag, st)
        if resp.status_code in (HTTPStatus.OK, HTTPStatus.CREATED):
            out = self._empty(HTTPStatus.CREATED)
            img = self.store.get(json.loads(resp.get_data())["ref"])
            if img.digest:
                out.headers["X-Image-Digest"] = img.digest
            return out
        return resp

    def _pin(self, parent: str) -> str | None:
        """Pin a `from` parent to a revision ref: an explicit `_vN` as is, a tag -> its newest."""
        p_name, _, p_version = parent.partition(":")
        return self.resolve(p_name, p_version or "latest")

    def _commit(self, user: str, name: str, tag: str, st: Staging, *,  # noqa: PLR0911, C901
                message: str = "") -> Response:
        """
        Turn a staging area into revision `tag_vN` (spec §2.3), atomically under the repo lock.

        What the area lacks (image, task/, attachments, sources) is taken from the newest revision.
        Same content as the newest revision -> nothing is created (200, `unchanged`). The new
        revision is assembled at its final paths and only then entered into the index; a failure
        in between removes what was moved, so the index never names a half-made revision.
        """
        ref_tag = f"{name}:{tag}"
        staged_dir = st.images.dir(name, tag)
        has_image = (staged_dir / "meta.json").is_file()
        staged_task = staged_dir / "task"
        with self.repo(name).locked() as idx:
            latest = idx.latest(tag)
            latest_ref = f"{name}:{revision_version(tag, latest.n)}" if latest else None
            if not has_image and latest_ref is None:
                if self.store.exists(ref_tag) and staged_task.is_dir():
                    return self._commit_unmigrated(name, tag, st)
                st.remove()
                return self._json(HTTPStatus.NOT_FOUND, {"error": f"нечего фиксировать: у {ref_tag} нет образа на пуле"})
            staged = st.images.get(ref_tag) if has_image else None
            image_digest = staged.digest if staged else latest.image_digest
            raw_parents = staged.parents if staged else latest.parents
            pinned: list[str] = []
            for parent in raw_parents:
                pin = self._pin(parent)
                if pin is None:
                    st.remove()
                    return self._json(HTTPStatus.CONFLICT, {"error": f"родитель {parent} не найден на пуле — отправьте его первым"})
                pinned.append(pin)
            if idx.visibility == "public":
                private = [p for p in pinned if self.repo(p.partition(":")[0]).visibility == "private"]
                if private:
                    st.remove()
                    return self._json(HTTPStatus.CONFLICT, {
                        "error": f"публичный образ нельзя строить на приватном ({', '.join(private)})"})
            t_digest = (task_digest(staged_task) if staged_task.is_dir()
                        else (latest.task_digest if latest else ""))
            raw_base = str(st.intent.get("base") or "")
            base = self._pin(raw_base) if raw_base else (
                self.store.get(latest_ref).base if latest_ref else None)
            if base and idx.visibility == "public" and self.repo(base.partition(":")[0]).visibility == "private":
                st.remove()
                return self._json(HTTPStatus.CONFLICT, {"error": f"публичный образ нельзя строить на приватной базе {base}"})
            if raw_base and base is None:
                st.remove()
                return self._json(HTTPStatus.CONFLICT, {"error": f"базовый образ {raw_base} не найден на пуле — отправьте его первым (hashpass push base)"})
            prev_base = self.store.get(latest_ref).base if latest_ref else None
            # attachments: compare the files only (their index records upload times)
            changed_files = any(
                _tree_digest(getattr(st, kind)._dir(ref_tag) / sub) not in (  # noqa: SLF001
                    None, _tree_digest(live._dir(latest_ref) / sub))           # noqa: SLF001
                for kind, live, sub in (("attachments", self.attachments(), "files"),
                                        ("sources", self.sources(), "."))
            ) if latest_ref else False
            if (latest is not None and not changed_files
                    and (image_digest, t_digest, tuple(pinned), base)
                    == (latest.image_digest, latest.task_digest, latest.parents, prev_base)):
                st.remove()
                return self._json(HTTPStatus.OK, {"ref": latest_ref, "n": latest.n, "unchanged": True})
            n = idx.peek_next(tag)
            version = revision_version(tag, n)
            ref = f"{name}:{version}"
            dest = self.store.dir(name, version)
            att_dest = self.attachments().ref_path(ref)
            src_dest = self.sources()._dir(ref)            # noqa: SLF001  (same package)
            try:
                self._assemble(st, name, tag, version, latest_ref, pinned, has_image=has_image)
                if base:
                    self._set_meta_field(dest, "base", base)
                idx.add(tag, {"image_digest": image_digest, "task_digest": t_digest,
                              "parents": pinned, "by": user, "message": message})
            except (OSError, ValueError, KeyError, tarfile.TarError) as exc:
                for d in (dest, att_dest, src_dest):
                    shutil.rmtree(d, ignore_errors=True)
                return self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"версия {ref} не создана: {exc}"})
        intent = st.intent
        st.remove()
        self._catalog_on_commit(name, tag, t_digest, image_digest, intent)
        return self._json(HTTPStatus.CREATED, {"ref": ref, "n": n})

    def _commit_unmigrated(self, name: str, tag: str, st: Staging) -> Response:
        """Update a record stored before revisions (`name:tag` itself) with its task, in place."""
        ref_tag = f"{name}:{tag}"
        task_dir = self.store.get(ref_tag).layer.parent / "task"
        incoming = task_dir.with_name(f"task.incoming-{st.sid}")
        old = task_dir.with_name(f"task.old-{st.sid}")
        shutil.move(st.images.dir(name, tag) / "task", incoming)   # next to it: same filesystem
        if task_dir.exists():
            task_dir.rename(old)                       # the working grader stays until the swap
        incoming.rename(task_dir)
        shutil.rmtree(old, ignore_errors=True)
        intent = st.intent
        st.remove()
        self._catalog_on_commit(name, tag, task_digest(task_dir), self._image_digest(ref_tag), intent)
        return self._json(HTTPStatus.CREATED, {"ref": ref_tag, "n": 0})

    def _assemble(self, st: Staging, name: str, tag: str, version: str,  # noqa: PLR0913, PLR0917
                  latest_ref: str | None, pinned: list[str], *, has_image: bool) -> None:
        """Move/copy the area's parts to revision `version`'s final paths."""
        ref_tag, ref = f"{name}:{tag}", f"{name}:{version}"
        staged_dir = st.images.dir(name, tag)
        dest = self.store.dir(name, version)
        if dest.exists():
            msg = f"{ref} уже существует"
            raise ValueError(msg)
        if has_image:
            dest.parent.mkdir(parents=True, exist_ok=True)
            staged_dir.rename(dest)
            meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
            meta.update({"name": name, "version": version, "parents": pinned})
            (dest / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            if not (dest / "task").is_dir() and latest_ref is not None:
                prev_task = self.store.get(latest_ref).layer.parent / "task"
                if prev_task.is_dir():
                    shutil.copytree(prev_task, dest / "task", symlinks=True)
        else:
            self.store.link_revision(latest_ref, name, version, parents=tuple(pinned))
            if (staged_dir / "task").is_dir():
                shutil.rmtree(dest / "task", ignore_errors=True)
                (staged_dir / "task").rename(dest / "task")
        for kind, live in (("attachments", self.attachments()), ("sources", self.sources())):
            staged_store = getattr(st, kind)
            src = staged_store._dir(ref_tag)                 # noqa: SLF001
            out = live._dir(ref)                             # noqa: SLF001
            out.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.move(src, out)                        # may cross filesystems (attachments_path)
            elif latest_ref is not None and live._dir(latest_ref).is_dir():  # noqa: SLF001
                shutil.copytree(live._dir(latest_ref), out, symlinks=True)  # noqa: SLF001

    @staticmethod
    def _set_meta_field(image_dir: Path, key: str, value: str) -> None:
        meta = json.loads((image_dir / "meta.json").read_text(encoding="utf-8"))
        meta[key] = value
        (image_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def _catalog_on_commit(self, name: str, tag: str, t_digest: str, image: str, intent: dict) -> None:
        """Put a new revision of a catalogued tag up for moderation; `publish` adds it first."""
        ref_tag = f"{name}:{tag}"
        if not (intent.get("publish") or self.catalog().find(ref_tag) is not None):
            return
        self.catalog().add_task(ref_tag, t_digest, auto=self._auto_approved(name), image=image,
                                block_name=(intent.get("block") or None) if intent.get("publish") else None)

    def _route_closure(self, tail: str) -> Response:  # noqa: PLR0911
        """
        Return the `from` chain of the revision this caller gets, ancestors first.

        `?revisions=1` (a revision-aware client): pinned revision refs + each one's parents. An old
        client gets tag names (`x:1`), which it fetches one by one as before.
        """
        parts = self._split_ref(tail)
        if parts is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        name, version = parts
        ref = f"{name}:{version}"
        served = self._view_revision(self._token_user(), name, version)
        if served is None:
            return self._not_found(ref)
        if served.startswith(_COPY):                  # the copy's own `from` chain, then the ref
            try:
                refs = [r for p in ApprovedStore(Path(self.store.root) / "approved").parents(ref)
                        for r in closure_refs(p, self.store)]
            except KeyError as exc:
                return self._not_found(str(exc.args[0]) if exc.args else ref)
            return self._json(HTTPStatus.OK, {"refs": [*dict.fromkeys(refs), ref]})
        try:
            refs = closure_refs(served, self.store)
        except KeyError as exc:                 # one of its parents is missing
            missing = str(exc.args[0]) if exc.args else ref
            return self._not_found(missing)
        if request.args.get("revisions") == "1":
            bases = {r: b for r in refs if (b := self.store.get(r).base) and self.store.exists(b)}
            try:                                      # the pinned bases come first, with their chains
                below = [x for b in dict.fromkeys(bases.values()) for x in closure_refs(b, self.store)]
            except KeyError:
                below = []
            refs = list(dict.fromkeys([*below, *refs]))
            return self._json(HTTPStatus.OK, {"refs": refs, "bases": bases, "parents": {
                r: list(self.store.get(r).parents) for r in refs}})
        legacy = [_tag_ref(r) for r in refs[:-1]] + [ref]
        return self._json(HTTPStatus.OK, {"refs": list(dict.fromkeys(legacy))})

    def _route_attachment_put(self, tail: str) -> Response:
        parts = self._split_ref(tail)
        if parts is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        name, version = parts
        user, err = self._authorize_write(name, version)
        if err is not None:
            return err
        target, ref = self._ref_target(user, name, version, "attachments")
        if target is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        filename = request.args.get("name", "")
        body = request.get_data(cache=False, as_text=False)
        if not filename or not body or len(body) > _MAX_ATTACH:
            return self._empty(HTTPStatus.BAD_REQUEST)
        taskfile = request.args.get("taskfile", "") == "1"
        try:
            target.put_file(ref, filename, body, taskfile=taskfile)
        except (ValueError, OSError):
            return self._empty(HTTPStatus.BAD_REQUEST)
        return self._empty(HTTPStatus.CREATED)

    def _route_attachment_get(self, tail: str) -> Response:
        """
        Serve one attachment (Taskfile, source.tar.gz) to any author or admin -- never a student.

        Like the web card's download: an author may READ another author's task sources (to learn
        from them, or to see why a task refuses an answer), but writes stay namespace-bound.
        """
        parts = self._split_ref(tail)
        if parts is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        name, version = parts
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        if not self._may_read_sources(user, name, request.args.get("name", "")):
            return self._empty(HTTPStatus.FORBIDDEN)
        try:
            blob = self.attachments().read_file(self._live_ref(f"{name}:{version}"),
                                                request.args.get("name", ""))
        except (ValueError, FileNotFoundError, OSError):
            return self._empty(HTTPStatus.NOT_FOUND)
        return Response(blob, status=HTTPStatus.OK, mimetype="application/octet-stream")

    def _route_source(self, tail: str) -> Response:  # noqa: PLR0911
        """
        Serve a task's sources as files.

        PUT a tar.gz (namespace owner/admin); GET the listing, one file (`?path=`) or the whole
        tree as a tar.gz (`?archive=1`) -- any author or admin, never a student.
        """
        parts = self._split_ref(tail)
        if parts is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        name, version = parts
        ref = f"{name}:{version}"
        if request.method == "PUT":
            user, err = self._authorize_write(name, version)
            if err is not None:
                return err
            target, put_ref = self._ref_target(user, name, version, "sources")
            if target is None:
                return self._empty(HTTPStatus.NOT_FOUND)
            body = request.get_data(cache=False, as_text=False)
            if not body or len(body) > _MAX_ATTACH:
                return self._empty(HTTPStatus.BAD_REQUEST)
            try:
                target.put_archive(put_ref, body)
            except (ValueError, OSError, tarfile.TarError):
                return self._empty(HTTPStatus.BAD_REQUEST)
            return self._empty(HTTPStatus.CREATED)
        return self._source_get(self._live_ref(ref))

    def _source_get(self, ref: str) -> Response:  # noqa: PLR0911
        """GET a task's sources: listing, one file (`?path=`) or the archive (`?archive=1`)."""
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        if not self._may_read_sources(user, ref.partition(":")[0], request.args.get("path", "")):
            return self._empty(HTTPStatus.FORBIDDEN)
        if not self._sources_ready(ref):
            return self._not_found(ref)               # an old pool push: the viewer shows the Taskfile
        src = self.sources()
        try:
            if "path" in request.args:
                return Response(src.read(ref, request.args["path"]), status=HTTPStatus.OK,
                                mimetype="application/octet-stream")
            if request.args.get("archive") == "1":
                return self._blob(HTTPStatus.OK, src.archive(ref))
            return self._json(HTTPStatus.OK, {"files": src.listing(ref)})
        except (ValueError, FileNotFoundError, OSError):
            return self._empty(HTTPStatus.NOT_FOUND)

    # -- routes: web dashboard ---------------------------------------------

    def _web_dashboard(self) -> Response:
        if era.courses_on():   # progress lives in each course now
            return self._redirect("/c")
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        group = request.args.get("group") or None
        profiles = self.users.all_users()
        attempts = self.attempts()
        return self._html(render_dashboard(
            profiles,
            [e.as_dict() for e in self.catalog().entries()],
            self.progress().all(), group=group,
            attempts={str(p["user"]): attempts.summary(str(p["user"])) for p in profiles}))

    def _web_users(self) -> Response:
        actor = self._session_role(("admin",))
        if actor is None:
            return self._redirect("/web/login")
        q = request.args.get("q", "").strip()
        return self._html(render_users(
            self.users.search(q) if q else self.users.all_users(),
            registration_open=self.config.registration_open, current_user=actor,
            pool_auto=self.pool_settings().auto_approve, q=q,
            deletions=[r for r in self.deletions().all() if r["state"] == "open"]))

    def _web_users_auto_approve(self) -> Response:
        """Admin: switch one author's auto-approval (own included)."""
        if self._session_role(("admin",)) is None:
            return self._redirect("/web/login")
        target = request.form.get("user", "").strip()
        if self.users.has(target):
            self.users.set_auto_approve(target, on=request.form.get("on") == "1")
        return self._redirect("/web/users")

    def _web_pool_auto_approve(self) -> Response:
        """Admin: switch auto-approval for the whole pool."""
        if self._session_role(("admin",)) is None:
            return self._redirect("/web/login")
        self.pool_settings().set_auto_approve(on=request.form.get("on") == "1")
        return self._redirect("/web/users")

    def _web_images(self) -> Response:
        if era.courses_on():   # tasks/images: search and user pages
            return self._redirect("/search?type=tasks")
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        blocks = [b.as_dict() for b in self.catalog().blocks()]
        return self._html(render_catalog(self._pool_image_rows(), blocks))

    def _web_image_card(self, ref: str) -> Response:
        viewer = self._session_user()
        courses_on = era.courses_on()
        if viewer is None or (not courses_on and self.users.role(viewer) not in _AUTHOR_ROLES):
            return self._redirect(f"/web/login?next={quote('/web/image/' + ref, safe='')}")
        ref = self._live_ref(ref)
        if not self.store.exists(ref) or not self._may_see_repo(viewer, ref.partition(":")[0]):
            return self._web_not_found(ref)
        row = next((r for r in self._pool_image_rows() if r["ref"] == ref), None)
        if row is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        entry = self.catalog().find(_tag_ref(ref))
        row = {**row, "hidden": entry.hidden if entry else False,
               "sources": self.sources().listing(ref) if self._sources_ready(ref) else [],
               **({"state": entry.state, "reason": entry.reason,
                   "pending_update": entry.as_dict()["pending_update"]} if entry else {})}
        return self._html(render_image_card(row, **self._card_extra(viewer, ref)))

    def _card_extra(self, viewer: str, ref: str) -> dict[str, object]:
        """Revisions, settings, where used, proposals and merges for an image card (spec §11)."""
        name, _, version = ref.partition(":")
        tag, n, _latest = parse_version(version)
        idx = self.repo(name)
        role = self.users.role(viewer)
        owner = self._may_write(viewer, name)
        merges = self.merges(name).all() if owner else [m for m in self.merges(name).all() if m["by"] == viewer]
        open_merges = []
        for m in merges:
            row = dict(m)
            if m["state"] == "open" and owner:
                base = self.resolve(name, m["to_tag"])
                row["files"] = tree_diff(self.sources()._dir(base) if base else None,  # noqa: SLF001
                                         self.sources()._dir(m["from"]))           # noqa: SLF001
            open_merges.append(row)
        origin = idx.fork_of.partition(":")[0]
        return {
            "repo": name, "tag": tag, "n": n, "repo_info": idx.as_dict() if idx.exists else None,
            "owner": owner, "courses_era": era.courses_on(),
            "used_in": self.people.where_used(name, tag, viewer=viewer, role=role,
                                              see_all=owner or role == "admin"),
            "propose_to": [c.ref for c in self.course_api.courses.all() if can(viewer, role, c, "propose")
                           and c.find_task(name, tag) is None],
            "may_fork": self._may_read_sources(viewer, name) and not owner and n is not None,
            "fork_origin": origin if origin and owner else "",
            "merges": open_merges, "viewer": viewer,
            "people": [{"user": _owner_of(name), "role": "owner"}] + [
                {"user": u, "role": r} for u, r in sorted(idx.members.items())] if _owner_of(name) else [],
            "may_people": self._repo_level(viewer, name) >= OWNER,
            "role_ru": {"owner": "владелец", "maintainer": "сопровождающий", "author": "автор", "member": "участник"},
        }

    def _web_source_file(self) -> Response:  # noqa: PLR0911  (page / folder / raw / download)
        """
        Show a task's source folder or file as a page -- authors/admins.

        `raw=1` sends the file as plain text, `dl=1` as a download (GitHub's Raw / Download).
        """
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        ref, path = self._live_ref(request.args.get("ref", "")), request.args.get("path", "").strip("/")
        if not self._sources_ready(ref):
            return self._empty(HTTPStatus.NOT_FOUND)
        listing = self.sources().listing(ref)
        if not path or any(f["dir"] and f["path"] == path for f in listing):
            return self._html(render_source_file(ref, path, None, 0, sources=listing, is_dir=True))
        try:
            blob = self.sources().read(ref, path)
        except (ValueError, FileNotFoundError, OSError):
            return self._empty(HTTPStatus.NOT_FOUND)
        if request.args.get("dl") == "1":
            resp = Response(blob, status=200, mimetype="application/octet-stream")
            name = re.sub(r"[^\w.-]+", "-", path.rsplit("/", 1)[-1]) or "file"
            resp.headers["Content-Disposition"] = f'attachment; filename="{name}"'
            return resp
        try:
            text: str | None = blob.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        if request.args.get("raw") == "1":
            if text is None:
                return Response(blob, status=200, mimetype="application/octet-stream")
            return Response(text, status=200, mimetype="text/plain; charset=utf-8")
        return self._html(render_source_file(ref, path, text, len(blob)))

    def _web_source_archive(self) -> Response:
        """Send the task's sources as one tar.gz download -- authors/admins."""
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        ref = self._live_ref(request.args.get("ref", ""))
        try:
            blob = self.sources().archive(ref)
        except (ValueError, FileNotFoundError, OSError):
            return self._empty(HTTPStatus.NOT_FOUND)
        resp = Response(blob, status=200, mimetype="application/gzip")
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", ref).strip("-") or "source"
        resp.headers["Content-Disposition"] = f'attachment; filename="{name}.tar.gz"'
        return resp

    def _may_watch(self, viewer: str | None, student: str, ref: str) -> bool:
        """
        Tell whether `viewer` may read `student`'s commands on `ref`.

        Staff (old roles) may, and whoever adds tasks to a course `student` takes that holds
        `ref` -- work with the course.
        """
        if viewer is None:
            return False
        role = self.users.role(viewer)
        if role in _AUTHOR_ROLES:
            return True
        repo, _, tag = ref.partition(":")
        api = self.course_api
        taken = api.enrollments.of(student)
        return any(c.id in taken and c.find_task(repo, tag) is not None and can(viewer, role, c, "add")
                   for c in api.courses.all())

    def _web_history(self) -> Response:
        user, ref = request.args.get("user", ""), request.args.get("ref", "")
        viewer = self._session_user()
        if viewer is None:
            return self._redirect("/web/login")
        if not self._may_watch(viewer, user, ref):
            return self._empty(HTTPStatus.FORBIDDEN)
        record = self.progress().get(user).get(ref, {}) if user else {}
        sessions = self.attempts().sessions(user, ref) if user and ref else []
        return self._html(render_history(user, ref, record,
                                         ref_commands=self._reference_commands(ref),
                                         sessions=sessions))

    def _web_history_live(self) -> Response:
        """
        Answer the history page's poll: its live part as HTML + `X-History-Sig`, 204 when unchanged.

        The page asks every few seconds with the signature it has; a student typing changes it.
        """
        user, ref = request.args.get("user", ""), request.args.get("ref", "")
        if not self._may_watch(self._session_user(), user, ref):
            return self._empty(HTTPStatus.UNAUTHORIZED)
        record = self.progress().get(user).get(ref, {}) if user else {}
        sessions = self.attempts().sessions(user, ref) if user and ref else []
        body, sig = render_history_live(user, ref, record,
                                        ref_commands=self._reference_commands(ref),
                                        sessions=sessions)
        if request.args.get("sig") == sig:
            return self._empty(HTTPStatus.NO_CONTENT)
        resp = self._html(body)
        resp.headers["X-History-Sig"] = sig
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def _reference_commands(self, ref: str) -> list[str]:
        """Return the task's `solve` commands parsed from its Taskfile attachment, or []."""
        if not ref:
            return []
        att = self.attachments()
        for f in att.describe(ref).get("files", []) or []:
            if f.get("taskfile"):
                with contextlib.suppress(ValueError, FileNotFoundError, OSError):
                    return reference_commands(att.read_file(ref, f["name"]).decode("utf-8", "replace"))
        return []

    def _web_login_get(self) -> Response:
        # Already in, but an admin-only page sent us here: say so, or the form looks like a
        # lost session and the author logs in again -- in circles.
        user = self._session_user()
        courses = era.courses_on()
        next_url = _local_path(request.args.get("next", ""))
        if user is not None and next_url:
            return self._redirect(next_url)
        if user is not None:
            return self._html(render_login(signed_in=user, role=self.users.role(user), courses=courses))
        return self._html(render_login(next_url=next_url, courses=courses))

    def _web_login_post(self) -> Response:
        user = request.form.get("user", "").strip()
        courses = era.courses_on()     # with courses anyone signs in
        staff = self.users.role(user) in _AUTHOR_ROLES
        if self.users.verify(user, request.form.get("password", "")) and (staff or courses):
            token = issue_token(self.secret, user, now=time.time())
            home = f"/u/{quote(user, safe='')}" if courses else "/web"   # one's own page is home
            target = _local_path(request.form.get("next", "")) or home
            return self._redirect(target, set_cookie=("hp_session", token))
        return self._html(render_login("Неверный логин/пароль или нет доступа.",
                                       next_url=_local_path(request.form.get("next", "")),
                                       courses=courses),
                          status=HTTPStatus.UNAUTHORIZED)

    def _web_logout(self) -> Response:
        return self._redirect("/web/login", clear_cookie=True)

    def _settings_page(self, user: str, *, error: str = "", done: str = "") -> Response:
        tz = str((self.users.get(user) or {}).get("tz", ""))
        return self._html(render_settings(tz=tz, zones=_time_zones(), error=error, done=done))

    def _web_password_get(self) -> Response:
        user = self._session_user()
        if user is None:
            return self._redirect("/web/login")
        if request.args.get("photo") == "bad":
            return self._settings_page(user, error="фото не подошло: PNG, JPEG, GIF или WebP, до 2 МБ")
        return self._settings_page(user)

    def _web_settings_tz(self) -> Response:
        """Save the viewer's own time zone for the web pages ("" = the browser's)."""
        user = self._session_user()
        if user is None:
            return self._redirect("/web/login")
        tz = request.form.get("tz", "").strip()
        if tz and tz not in _time_zones():
            return self._settings_page(user, error="неизвестный часовой пояс")
        self.users.set_tz(user, tz)
        g.hp_tz = tz
        return self._settings_page(user, done="Часовой пояс сохранён.")

    def _web_password_post(self) -> Response:
        user = self._session_user()
        if user is None:
            return self._redirect("/web/login")
        new, confirm = request.form.get("new", ""), request.form.get("confirm", "")
        if not new or new != confirm:
            return self._settings_page(user, error="новые пароли пусты или не совпадают")
        if not self.users.verify(user, request.form.get("old", "")):
            return self._settings_page(user, error="неверный текущий пароль")
        try:
            validate_password(new)
        except WeakPasswordError as exc:
            return self._settings_page(user, error=str(exc))
        self.users.set_password(user, new)
        return self._settings_page(user, done="Пароль изменён.")

    def _web_user_profile(self, login: str) -> Response:
        """One user's profile: every catalog task with status, tries, time -- authors/admins."""
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        profile = self.users.get(login)
        if profile is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        attempts = self.attempts()
        attempts.prune(login)
        return self._html(render_profile(
            profile, [e.as_dict() for e in self.catalog().entries()],
            self.progress().get(login), attempts.by_task(login)))

    def _web_reset_get(self) -> Response:
        token = request.args.get("token", "")
        return self._html(render_reset_form(token))

    def _web_reset_post(self) -> Response:
        token = request.form.get("token", "")
        subject = verify_token(self.secret, token, now=time.time())
        if subject is None or not subject.startswith(_RESET_PREFIX):
            return self._html(render_reset_form(token, "ссылка недействительна или истекла"))
        new, confirm = request.form.get("new", ""), request.form.get("confirm", "")
        if not new or new != confirm:
            return self._html(render_reset_form(token, "пароли пусты или не совпадают"))
        try:
            validate_password(new)
        except WeakPasswordError as exc:
            return self._html(render_reset_form(token, str(exc)))
        try:
            self.users.set_password(subject[len(_RESET_PREFIX):], new)
        except KeyError:
            return self._html(render_reset_form(token, "пользователь не найден"))
        return self._redirect("/web/login")

    def _web_users_role(self) -> Response:
        actor = self._session_role(("admin",))
        if actor is None:
            return self._redirect("/web/login")
        target = request.form.get("user", "").strip()
        role = request.form.get("role", "")
        if target != actor and role in ROLES and self.users.has(target):
            self.users.set_role(target, role)   # never change your own role (self-lockout)
        return self._redirect("/web/users")

    def _web_users_group(self) -> Response:
        actor = self._session_role(("admin",))
        if actor is None:
            return self._redirect("/web/login")
        target = request.form.get("user", "").strip()
        group = request.form.get("group", "").strip()[:64]
        if self.users.has(target):
            with contextlib.suppress(KeyError):
                self.users.set_group(target, group)
        return self._inline_saved()

    def _web_users_comment(self) -> Response:
        actor = self._session_role(("admin",))
        if actor is None:
            return self._redirect("/web/login")
        target = request.form.get("user", "").strip()
        comment = request.form.get("comment", "").strip()[:_MAX_COMMENT]
        if self.users.has(target):
            with contextlib.suppress(KeyError):
                self.users.set_comment(target, comment)
        return self._inline_saved()

    def _inline_saved(self) -> Response:
        """Answer an inline edit: 204 to the page's background save (`?bg=1`), else back to the list."""
        if request.args.get("bg") == "1":
            return self._empty(HTTPStatus.NO_CONTENT)
        return self._redirect("/web/users")

    def _web_users_registration(self) -> Response:
        if self._session_role(("admin",)) is None:
            return self._redirect("/web/login")
        self.config.registration_open = request.form.get("open") == "true"
        if self.config_path is not None:
            save_config(self.config_path, self.config)
        return self._redirect("/web/users")

    def _web_users_reset_link(self) -> Response:
        if self._session_role(("admin",)) is None:
            return self._redirect("/web/login")
        target = request.form.get("user", "")
        if not self.users.has(target):
            return self._redirect("/web/users")
        token = issue_token(self.secret, _RESET_PREFIX + target,
                            now=time.time(), ttl=_RESET_TTL)
        return self._html(
            render_reset_link(target, f"{self._pool_url()}/web/reset?token={token}"))

    def _web_users_delete(self) -> Response:
        actor = self._session_role(("admin",))
        if actor is None:
            return self._redirect("/web/login")
        target = request.form.get("user", "").strip()
        if target and target != actor:                 # never delete yourself
            self.users.delete(target)
            self.progress().delete(target)
            self.attempts().delete_user(target)
        return self._redirect("/web/users")

    def _web_users_delete_group(self) -> Response:
        actor = self._session_role(("admin",))
        if actor is None:
            return self._redirect("/web/login")
        group = request.form.get("group", "").strip()
        if group:
            prog = self.progress()
            for profile in self.users.all_users():
                user = str(profile["user"])
                if str(profile.get("group", "")) == group and user != actor:
                    self.users.delete(user)
                    prog.delete(user)
                    self.attempts().delete_user(user)
        return self._redirect("/web/users")

    def _web_ref_form(self) -> tuple[str, str] | None:
        """Author-gate a POST, return (ref, form-ref) if the ref exists, else redirect (returns None)."""
        if self._session_role(_AUTHOR_ROLES) is None:
            return None
        ref = request.form.get("ref", "")
        if not ref or not self.store.exists(ref):
            return None
        return ref, ref

    @staticmethod
    def _card_url(ref: str) -> str:
        """Path to the image card page for one ref (URL-encoded, matches the /web/image/<ref> route)."""
        return f"/web/image/{quote(ref, safe='/:')}" if ref else "/web/images"

    def _web_not_found(self, ref: str) -> Response:
        """404 card page; links the ref's twins under other namespaces when there are any."""
        body = f"<p>образ «{html.escape(ref)}» не найден.</p>"
        suggestions = self.store.similar(ref)
        if suggestions:
            links = " или ".join(f'<a href="{html.escape(self._card_url(s))}">{html.escape(s)}</a>'
                                 for s in suggestions)
            body += f"<p>быть может, вы искали {links}?</p>"
        return self._html(body, status=HTTPStatus.NOT_FOUND)

    def _web_forbidden(self, name: str) -> Response:
        """Render a 403 page for a card/catalog write denied by ownership (same reason as the API)."""
        return self._html(_ownership_message(name), status=HTTPStatus.FORBIDDEN)

    def _web_image_attach(self) -> Response:
        user = self._session_role(_AUTHOR_ROLES)
        if user is None:
            return self._redirect("/web/login")
        ref = self._live_ref(request.form.get("ref", ""))
        name = ref.partition(":")[0]
        if ref and not self._may_write(user, name):
            return self._web_forbidden(name)
        upload = request.files.get("file")
        if ref and self.store.exists(ref) and upload and upload.filename:
            data = upload.read()
            if data and len(data) <= _MAX_ATTACH:
                with contextlib.suppress(ValueError, OSError):
                    self.attachments().put_file(ref, upload.filename, data)
        return self._redirect(self._card_url(ref))

    def _web_image_attach_delete(self) -> Response:
        user = self._session_role(_AUTHOR_ROLES)
        if user is None:
            return self._redirect("/web/login")
        ref = self._live_ref(request.form.get("ref", ""))
        if not ref or not self.store.exists(ref):
            return self._redirect("/web/images")
        name = ref.partition(":")[0]
        if not self._may_write(user, name):
            return self._web_forbidden(name)
        with contextlib.suppress(ValueError, OSError):
            self.attachments().delete_file(ref, request.form.get("name", ""))
        return self._redirect(self._card_url(ref))

    def _web_image_file(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        ref, name = self._live_ref(request.args.get("ref", "")), request.args.get("name", "")
        try:
            blob = self.attachments().read_file(ref, name)
            safe = safe_filename(name)
        except (ValueError, FileNotFoundError, OSError):
            return self._empty(HTTPStatus.NOT_FOUND)
        resp = Response(blob, status=200, mimetype="application/octet-stream")
        resp.headers["Content-Disposition"] = f'attachment; filename="{safe}"'
        return resp

    def _web_catalog_add(self) -> Response:
        user = self._session_role(_AUTHOR_ROLES)
        if user is None:
            return self._redirect("/web/login")
        ref = self._live_ref(request.form.get("ref", ""))
        if not ref or not self.store.exists(ref):
            return self._redirect("/web/images")
        name = ref.partition(":")[0]
        if not self._may_write(user, name):
            return self._web_forbidden(name)
        task_dir = self.store.get(ref).layer.parent / "task"
        if not task_dir.exists():   # only a task image (with a grader) can join the catalog
            return self._redirect("/web/images")
        self.catalog().add_task(_tag_ref(ref), task_digest(task_dir), auto=self._auto_approved(name),
                                image=self.store.get(ref).digest or "",
                                block_id=request.form.get("block_id") or None)
        return self._redirect("/web/images")

    def _web_catalog_remove(self) -> Response:
        user = self._session_role(_AUTHOR_ROLES)
        if user is None:
            return self._redirect("/web/login")
        ref = _tag_ref(request.form.get("ref", ""))
        name = ref.partition(":")[0]
        if ref and not self._may_write(user, name):
            return self._web_forbidden(name)
        if not ref or self.catalog().find(ref) is None:
            return self._redirect("/web/images")
        self.catalog().remove_task(ref)
        return self._redirect("/web/images")

    def _web_task_toggle(self) -> Response:
        user = self._session_role(_AUTHOR_ROLES)
        if user is None:
            return self._redirect("/web/login")
        ref = request.form.get("ref", "")
        if not ref:
            return self._redirect("/web/images")
        name = ref.partition(":")[0]
        if not self._may_write(user, name):
            return self._web_forbidden(name)
        self.catalog().set_task_hidden(_tag_ref(ref), hidden=request.form.get("hidden", "") == "1")
        return self._redirect("/web/images")

    def _web_catalog_layout(self) -> Response:
        """
        Rewrite the whole catalog layout (blocks + task order); an administrative operation.

        It can move or de-list ANY task, including ones an author doesn't own, so (unlike the
        per-ref add/remove/toggle routes, which stay `_may_write`-gated) this one is admin-only.
        """
        if self._session_role(("admin",)) is None:
            if self._session_role(_AUTHOR_ROLES) is not None:
                return self._html(_LAYOUT_ADMIN_ONLY, status=HTTPStatus.FORBIDDEN)
            return self._empty(HTTPStatus.UNAUTHORIZED)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict) or not isinstance(data.get("blocks"), list):
            return self._empty(HTTPStatus.BAD_REQUEST)
        self.catalog().set_layout(data["blocks"])
        return self._json(HTTPStatus.OK, {"ok": True})

    def _web_block_add(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        self.catalog().add_block(request.form.get("name", "").strip() or "Блок")
        return self._redirect("/web/images")

    def _web_block_rename(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        self.catalog().rename_block(request.form.get("block_id", ""),
                                    request.form.get("name", "").strip() or "Блок")
        return self._redirect("/web/images")

    def _web_block_remove(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        self.catalog().remove_block(request.form.get("block_id", ""))
        return self._redirect("/web/images")

    def _web_block_toggle(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        self.catalog().set_block_open(request.form.get("block_id", ""),
                                      open_=request.form.get("open", "") == "1")
        return self._redirect("/web/images")

    def _web_block_hide_tasks(self) -> Response:
        """Hide/show every task of a block at once -- only the ones this author may write."""
        user = self._session_role(_AUTHOR_ROLES)
        if user is None:
            return self._redirect("/web/login")
        self.catalog().set_block_tasks_hidden(
            request.form.get("block_id", ""), hidden=request.form.get("hidden", "") == "1",
            may=lambda ref: self._may_write(user, ref.partition(":")[0]))
        return self._redirect("/web/images")


_TLS_HANDSHAKE_TIMEOUT = 10.0   # seconds a client gets to finish its ClientHello/handshake


class _HandshakeInWorker(WSGIRequestHandler):
    """
    Request handler that performs the TLS handshake on the connection's OWN thread.

    Werkzeug wraps the listening socket with `do_handshake_on_connect=True`, so the handshake
    runs inside `accept()` -- on the single serving thread. One client that opens TCP and never
    sends a ClientHello (port scanners, half-open mobile connections: routine on a public IP)
    then blocks accept() forever; the backlog fills and every other login times out (that was
    the production hang: Recv-Q 129 on :8080). `make_server` turns handshake-on-accept off, and
    this handler does it here, bounded by a timeout, dropping only the offending client.
    """

    def handle(self) -> None:
        conn = self.connection
        if isinstance(conn, ssl.SSLSocket):
            try:
                conn.settimeout(_TLS_HANDSHAKE_TIMEOUT)
                conn.do_handshake()
                conn.settimeout(None)
            except OSError:           # SSLError / TimeoutError / ConnectionError: this client only
                return
        super().handle()


class InFlight:
    """
    WSGI wrapper counting requests whose response is not fully sent yet.

    A request stays «in flight» until the last byte of its body is handed to the server (a
    streamed blob too, not just until Flask pops the request context), or until its body is
    dropped (client gone). Not until werkzeug closes the body: before that it drains «the rest of
    the request» from the socket, which a client can hold forever or break with an error that
    skips the close -- prod's self-update once waited for idle() for good. The pool restarts for
    an update only when `idle()`.
    """

    def __init__(self, app: Callable[..., Iterable[bytes]]) -> None:
        """Wrap the WSGI `app`; nothing is in flight yet."""
        self._app = app
        self._lock = threading.Lock()
        self._count = 0

    def idle(self) -> bool:
        with self._lock:
            return self._count == 0

    def _done(self) -> None:
        with self._lock:
            self._count -= 1

    def __call__(self, environ: dict, start_response: Callable[..., object]) -> Iterable[bytes]:
        with self._lock:
            self._count += 1
        try:
            body = self._app(environ, start_response)
        except BaseException:
            self._done()
            raise
        return _Counted(body, self._done)


class _Counted:
    """A response body that reports «done» once: at its end, on close, or when it is dropped."""

    def __init__(self, body: Iterable[bytes], done: Callable[[], None]) -> None:
        self._body = body
        self._it = iter(body)
        self._done = done
        self._open = True

    def __iter__(self) -> "_Counted":
        return self

    def __next__(self) -> bytes:
        try:
            return next(self._it)
        except StopIteration:        # the last chunk was taken
            self._finish()
            raise
        except BaseException:
            self._finish()
            raise

    def close(self) -> None:
        try:
            close = getattr(self._body, "close", None)
            if close is not None:
                close()
        finally:
            self._finish()

    def _finish(self) -> None:
        if self._open:
            self._open = False
            self._done()

    def __del__(self) -> None:       # the server dropped it without close (client gone mid-send)
        self._finish()


def make_server(store: ImageStore, users: UserStore, secret: bytes, *,   # noqa: PLR0913
                host: str = "127.0.0.1", port: int = 0,
                config: ServerConfig | None = None,
                config_path: Path | None = None,
                catalog_path: Path | None = None,
                progress_path: Path | None = None, attachments_path: Path | None = None,
                certfile: Path | None = None, keyfile: Path | None = None):
    """
    Create a pool registry server (port 0 = ephemeral). Default host is loopback.

    Returns a werkzeug WSGI server (`serve_forever` / `shutdown` / `server_address` /
    `server_close`), backing the same Flask app. With `certfile`+`keyfile`, the listener
    is TLS-wrapped (HTTPS) via stdlib `ssl` — same behavior as the previous stdlib server.
    """
    pool = PoolServer(store=store, users=users, secret=secret, config=config,
                      config_path=config_path, catalog_path=catalog_path,
                      progress_path=progress_path, attachments_path=attachments_path)
    ssl_context = (str(certfile), str(keyfile)) if certfile is not None and keyfile is not None else None
    if port != 0:
        # Werkzeug's make_server sys.exit(1)s on bind failure; do a preflight bind so a busy port
        # surfaces to callers as OSError (the previous stdlib server behaved this way, and tests
        # rely on it -- e.g. the admin seed must be skipped when the pool can't bind).
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, port))
    in_flight = InFlight(pool.app)
    server = _wsgi_make_server(host, port, in_flight, threaded=True, ssl_context=ssl_context,
                               request_handler=_HandshakeInWorker if ssl_context else None)
    if ssl_context is not None:
        # Accepted sockets are handed to the worker thread UN-handshaken; _HandshakeInWorker
        # finishes them there (see its docstring) -- the accept loop never waits on a client.
        server.socket.do_handshake_on_connect = False
    server.pool = pool         # let callers/tests reach the state directly (matches the old attrs)
    server.idle = in_flight.idle   # no response still being sent (self-update waits for this)
    return server
