"""hashpass CLI: a Docker-style command-line front end over build/run/registry."""
import argparse
import getpass
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from hashpass.build import build, run_image
from hashpass.imagestore.store import ImageStore
from hashpass.progress import current_stage
from hashpass.recipe.model import Recipe, image_ref, is_task
from hashpass.recipe.parse import load_recipe
from hashpass.registry.creds import CredentialCache
from hashpass.registry.remote import RemoteRegistry
from hashpass.taskbuild import build_task
from hashpass.taskrun import run_task

_ENV_HOME = "HASHPASS_HOME"
_HOME_DIRNAME = ".hashpass"
_IMAGES_DIRNAME = "images"
_BASE_DIRNAME = "base"
_BASE_TARNAME = "rootfs.tar"
_CREDS_NAME = "creds.json"
_WORK_DIRNAME = "work"
_DOCKER = "docker"
_BASE_IMAGE = "debian:trixie-slim"
_DEFAULT_STUDENT = "local"
_STOP_WORDS = frozenset({"exit", "quit"})
_COL_GAP = "  "
_HEADER = ("REF", "KIND")


@dataclass(frozen=True)
class Home:
    """Resolved hashpass home root plus its images/base/creds/work sub-paths."""

    root: Path

    @property
    def images(self) -> Path:
        return self.root / _IMAGES_DIRNAME

    @property
    def base_tar(self) -> Path:
        return self.root / _BASE_DIRNAME / _BASE_TARNAME

    @property
    def creds(self) -> Path:
        return self.root / _CREDS_NAME

    @property
    def work(self) -> Path:
        return self.root / _WORK_DIRNAME


@dataclass(frozen=True)
class Io:
    """Injected console I/O for the interactive loop (defaults wired to stdin/stdout/clock)."""

    read: Callable[[str], str | None]
    write: Callable[[str], object]
    clock: Callable[[], str]


def resolve_root(environ: Mapping[str, str], *, default_home: Path) -> Path:
    """Resolve the hashpass home root: $HASHPASS_HOME if set, else <default_home>/.hashpass."""
    override = environ.get(_ENV_HOME)
    return Path(override) if override else default_home / _HOME_DIRNAME


def build_env(environ: Mapping[str, str] | None = None, *, default_home: Path | None = None) -> Home:
    """Resolve the home from the environment and ensure its images/ dir exists."""
    environ = os.environ if environ is None else environ
    default_home = Path.home() if default_home is None else default_home
    home = Home(resolve_root(environ, default_home=default_home))
    home.images.mkdir(parents=True, exist_ok=True)
    return home


def _now_iso() -> str:
    """Return the current local time as an ISO-8601 string (the session timestamp source)."""
    return datetime.now().isoformat()


def _safe_input(prompt: str) -> str | None:
    """Read one line; EOF (Ctrl-D / closed stdin) becomes None so the loop stops cleanly."""
    try:
        return input(prompt)
    except EOFError:
        return None


def _default_io() -> Io:
    """Return the production console wiring: input, stdout, and the local clock."""
    return Io(read=_safe_input, write=sys.stdout.write, clock=_now_iso)


def ensure_base_tar(dest: Path, *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                    which: Callable[[str], str | None] = shutil.which) -> Path:
    """Ensure the base rootfs tarball exists; export it once via docker if missing."""
    if dest.exists():
        return dest
    if which(_DOCKER) is None:
        msg = "docker is required to export the base rootfs (install docker, or prepare <home>/base/rootfs.tar)"
        raise RuntimeError(msg)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cid = run([_DOCKER, "create", _BASE_IMAGE], capture_output=True, text=True,
              encoding="utf-8", check=True).stdout.strip()
    try:
        run([_DOCKER, "export", cid, "-o", str(dest)], check=True)
    finally:
        run([_DOCKER, "rm", cid], check=True, capture_output=True)
    return dest


def _kind(store: ImageStore, ref: str) -> str:
    """Classify a stored ref as a task (has a task/ artifacts dir) or a bare image."""
    return "task" if (store.get(ref).layer.parent / "task").exists() else "image"


def format_image_rows(rows: list[tuple[str, str]]) -> str:
    """Format (ref, kind) rows as a Docker-like two-column table (header always emitted)."""
    width = max((len(ref) for ref, _ in rows), default=0)
    width = max(width, len(_HEADER[0]))
    lines = [f"{_HEADER[0]:<{width}}{_COL_GAP}{_HEADER[1]}"]
    lines += [f"{ref:<{width}}{_COL_GAP}{kind}" for ref, kind in rows]
    return "\n".join(lines) + "\n"


def cmd_images(env: Home) -> int:
    """List built images and tasks (name:version + kind)."""
    store = ImageStore(env.images)
    rows = [(ref, _kind(store, ref)) for ref in store.list()]
    sys.stdout.write(format_image_rows(rows))
    return 0


def select_index(text: str | None, count: int) -> int | None:
    """Parse a 1-based menu choice to a 0-based index; blank/EOF/non-digit/out-of-range -> None."""
    if text is None:
        return None
    stripped = text.strip()
    if not stripped.isdigit():
        return None
    idx = int(stripped) - 1
    return idx if 0 <= idx < count else None


def _stage_prompt(session: object) -> str:
    """Return the shell-like prompt for the current stage (`hashpass:<task> [stage N/M]$ `)."""
    stage = current_stage(session.progress)
    total = len(session.progress.statuses)
    if stage is None:
        return f"hashpass:{session.task_id} [done]$ "
    return f"hashpass:{session.task_id} [stage {stage + 1}/{total}]$ "


def interact(session: object, *, read: Callable[[str], str | None],
             write: Callable[[str], object], clock: Callable[[], str]) -> None:
    """
    Drive one interactive task session: prompt, feed, and report stage progress.

    `read(prompt)` returns the next student line (None/EOF or a stop word ends the loop);
    each line is fed with a `clock()` timestamp; `write` emits the structural pass/complete
    lines. Narrative (say/show/voice/hint) is rendered by the session's own Renderer sink
    (in the CLI, the same stdout `write`), so a fired hint is shown by feed, not re-printed.
    """
    session.enter()
    while current_stage(session.progress) is not None:
        line = read(_stage_prompt(session))
        if line is None or line.strip() in _STOP_WORDS:
            break
        res = session.feed(line, ts=clock())
        if res.advanced:
            write(f"✓ stage passed  {res.local_key}\n")
            if current_stage(session.progress) is None:
                write("✓ all stages passed — task complete\n")


def _progress(msg: str) -> None:
    """Print a live build-progress line (flushed so it shows as the build runs)."""
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def resolve_ref(recipe: Recipe, tag: str | None, taskfile: Path) -> tuple[str, str]:
    """Resolve name:version: `-t` wins, else the recipe's `image` name, else the Taskfile's dir."""
    if tag:
        name, sep, version = tag.partition(":")
        return name, (version if sep else "latest")
    if recipe.name:
        return recipe.name, recipe.version
    return taskfile.resolve().parent.name, "latest"


def cmd_build(env: Home, taskfile: str, tag: str | None = None) -> int:
    """Build an image or a task from a Taskfile (auto-exporting the base rootfs on first use)."""
    recipe = load_recipe(Path(taskfile))
    name, version = resolve_ref(recipe, tag, Path(taskfile))
    recipe = replace(recipe, name=name, version=version)
    ensure_base_tar(env.base_tar)
    store = ImageStore(env.images)
    ref = image_ref(recipe)
    if is_task(recipe):
        build_task(recipe, store, base_tar=env.base_tar, workdir=env.work / "build", progress=_progress)
        kind = "task"
    else:
        build(recipe, store, base_tar=env.base_tar, workdir=env.work / "build", progress=_progress)
        kind = "image"
    sys.stdout.write(f"✓ built {kind} {ref}\n")
    return 0


def _run_task(env: Home, ref: str, store: ImageStore, io: Io) -> int:
    """Open a live task session and drive it through the interactive REPL, then tear down."""
    session = run_task(ref, store, env.work / "run", base_tar=env.base_tar,
                       student_id=_DEFAULT_STUDENT, nonce=uuid.uuid4().hex,
                       sink=io.write, sleep=time.sleep)
    try:
        interact(session, read=io.read, write=io.write, clock=io.clock)
    finally:
        session.teardown()
    return 0


def _run_image(env: Home, ref: str, store: ImageStore) -> int:
    """Open an interactive `/bin/sh` in the booted image machine (inherited stdio), then tear down."""
    runner = run_image(ref, store, env.work / "run", base_tar=env.base_tar)
    try:
        subprocess.run(["sudo", "machinectl", "shell", runner.machine, "/bin/sh"], check=False)
    finally:
        runner.teardown()
    return 0


def cmd_run(env: Home, ref: str, io: Io | None = None) -> int:
    """Run a task (interactive student session) or a bare image (interactive shell)."""
    io = io or _default_io()
    store = ImageStore(env.images)
    try:
        stored = store.get(ref)
    except KeyError:
        io.write(f"no such image: {ref}\n")
        return 1
    ensure_base_tar(env.base_tar)  # run needs the base rootfs too — a pull doesn't transfer it
    if (stored.layer.parent / "task").exists():
        return _run_task(env, ref, store, io)
    return _run_image(env, ref, store)


def cmd_login(env: Home, registry: str, user: str | None) -> int:
    """Prompt for credentials, authenticate to a registry, and cache the returned token."""
    user = user or input("Username: ")
    password = getpass.getpass("Password: ")
    cache = CredentialCache(env.creds)
    try:
        RemoteRegistry(registry, cache=cache).login(user, password)
    except urllib.error.URLError as exc:
        sys.stdout.write(f"login failed: {exc}\n")
        return 1
    sys.stdout.write(f"login succeeded — token cached for {registry}\n")
    return 0


def cmd_push(env: Home, ref: str, registry: str) -> int:
    """Push a ref and its `from` closure to a registry (using the cached login token)."""
    store = ImageStore(env.images)
    cache = CredentialCache(env.creds)
    copied = RemoteRegistry(registry, cache=cache).push(store, ref)
    sys.stdout.write(f"pushed {ref} ({len(copied)} layer(s))\n")
    return 0


def cmd_pull(env: Home, ref: str, registry: str) -> int:
    """Pull a ref and its `from` closure from a registry (anonymous)."""
    store = ImageStore(env.images)
    copied = RemoteRegistry(registry).pull(ref, store)
    sys.stdout.write(f"pulled {ref} ({len(copied)} layer(s))\n")
    return 0


def task_mode(env: Home, io: Io | None = None) -> int:
    """No-arg mode: list the built tasks, let the user pick one by number, and run it."""
    io = io or _default_io()
    store = ImageStore(env.images)
    tasks = [ref for ref in store.list() if _kind(store, ref) == "task"]
    if not tasks:
        io.write("no tasks built yet — `hashpass build <Taskfile>` first\n")
        return 0
    for i, ref in enumerate(tasks, 1):
        io.write(f"{i}. {ref}\n")
    idx = select_index(io.read("pick a task # (blank to quit): "), len(tasks))
    if idx is None:
        return 0
    return cmd_run(env, tasks[idx], io)


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser with one sub-parser per command."""
    parser = argparse.ArgumentParser(prog="hashpass",
                                     description="Author, build, and run hashpass tasks.")
    sub = parser.add_subparsers(dest="command")
    p_build = sub.add_parser("build", help="build an image/task from a Taskfile")
    p_build.add_argument("taskfile")
    p_build.add_argument("-t", "--tag", help="name[:version] (overrides the Taskfile's image line)")
    p_run = sub.add_parser("run", help="run a task (interactive) or a bare image (shell)")
    p_run.add_argument("ref")
    sub.add_parser("images", help="list built images and tasks")
    p_login = sub.add_parser("login", help="log in to a registry (caches a token)")
    p_login.add_argument("registry")
    p_login.add_argument("-u", "--user")
    p_push = sub.add_parser("push", help="push an image/task to a registry")
    p_push.add_argument("ref")
    p_push.add_argument("registry")
    p_pull = sub.add_parser("pull", help="pull an image/task from a registry")
    p_pull.add_argument("ref")
    p_pull.add_argument("registry")
    return parser


def _dispatch(env: Home, args: argparse.Namespace) -> int:
    """Route a parsed (non-empty) sub-command to its handler."""
    command = args.command
    if command == "build":
        return cmd_build(env, args.taskfile, args.tag)
    if command == "run":
        return cmd_run(env, args.ref)
    if command == "images":
        return cmd_images(env)
    if command == "login":
        return cmd_login(env, args.registry, args.user)
    if command == "push":
        return cmd_push(env, args.ref, args.registry)
    return cmd_pull(env, args.ref, args.registry)


_EXIT_ABORTED = 130  # conventional shell exit code for Ctrl-C / EOF


def main(argv: Sequence[str] | None = None) -> int:
    """Parse args and dispatch; no sub-command drops into interactive task mode."""
    args = build_parser().parse_args(argv)
    try:
        env = build_env()
        if args.command is None:
            return task_mode(env)
        return _dispatch(env, args)
    except (KeyboardInterrupt, EOFError):
        sys.stderr.write("\nhashpass: aborted\n")
        return _EXIT_ABORTED
    except (OSError, ValueError, RuntimeError, KeyError,
            urllib.error.URLError, subprocess.CalledProcessError) as exc:
        # never dump a traceback on an ordinary user error (bad Taskfile, no docker,
        # push-before-login, unknown ref, bad URL, a failed build step).
        sys.stderr.write(f"hashpass: {exc}\n")
        return 1
