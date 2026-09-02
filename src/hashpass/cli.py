"""hashpass CLI: a Docker-style command-line front end over build/run/registry."""
import argparse
import contextlib
import getpass
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from hashpass.build import build, run_image
from hashpass.image.base import build_base
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
_BASE_IMAGE = "debian:trixie-slim"  # slim boots + runs machinectl-shell commands reliably;
# full debian:trixie breaks command execution in the booted machine (and adds no ps/systemd).
_BASE_NAME = "debian"
_BASE_VERSION = "trixie"
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


def ensure_base_image(env: Home, store: ImageStore, *,
                      run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                      which: Callable[[str], str | None] = shutil.which) -> Path:
    """
    Ensure the single base image `debian:trixie` exists in the store; build it once.

    Exports the Debian rootfs (once), bakes it bootable + interactive (systemd, procps,
    fish, runtime) via build_base, and stores it as the parentless `debian:trixie` image
    that every build/run stacks on. Returns the stored base layer directory.
    """
    ref = f"{_BASE_NAME}:{_BASE_VERSION}"
    try:
        return store.get(ref).layer
    except KeyError:
        pass
    ensure_base_tar(env.base_tar, run=run, which=which)
    built = build_base(env.work / "base-build", from_tar=env.base_tar)
    store.save(_BASE_NAME, _BASE_VERSION, built, (), sudo=True)  # root-owned rootfs -> sudo rsync
    return store.get(ref).layer


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
    store = ImageStore(env.images)
    base = ensure_base_image(env, store)
    ref = image_ref(recipe)
    if is_task(recipe):
        build_task(recipe, store, base=base, workdir=env.work / "build", progress=_progress)
        kind = "task"
    else:
        build(recipe, store, base=base, workdir=env.work / "build", progress=_progress)
        kind = "image"
    sys.stdout.write(f"✓ built {kind} {ref}\n")
    return 0


def _announce_stage(session: object, io: Io) -> None:
    """Print the current stage number and its goal (the system talking to the student)."""
    stage = current_stage(session.progress)
    if stage is None:
        return
    total = len(session.meta.stages)
    io.write(f"\n\u2500\u2500 stage {stage + 1}/{total} \u2500\u2500  "
             f"{session.meta.stages[stage].message}\n")


def _advance_and_announce(session: object, io: Io) -> bool:
    """
    Grade the current stage against the live FS once; announce a pass + next goal.

    Returns whether a stage advanced (so callers can drain multiple completed stages).
    """
    try:
        res = session.check_current(ts=io.clock())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
        return False
    if not res.advanced:
        return False
    io.write(f"\n\u2713 stage passed  {res.local_key}\n")
    if current_stage(session.progress) is None:
        io.write("\u2713 all stages passed \u2014 task complete\n")
    else:
        session.enter()
        _announce_stage(session, io)
    return True


_MACHINE_PREFIX = "hp-"   # hostname-valid machine-name prefix for the interactive boot
_MACHINE_HEX = 12         # hex chars of uuid entropy in the machine name
_DEFAULT_TERM = "xterm-256color"
_GRADE_HOST = "127.0.0.1"  # per-command grade server binds loopback (shared with the container)
_ACCEPT_POLL = 0.3         # accept() timeout so the grade thread can notice `stop`
_GRADER_JOIN = 3.0         # seconds to let the grade thread finish after the console closes


def _sink_noop(_text: str) -> None:
    """Swallow output -- a no-op sink used while nothing should reach the terminal."""


class _Router:
    """A write sink whose destination can be swapped -- host stdout, or a per-command buffer."""

    def __init__(self, target: Callable[[str], object]) -> None:
        self._target = target

    def write(self, text: str) -> object:
        return self._target(text)

    def to(self, target: Callable[[str], object]) -> None:
        self._target = target


def _grade_server(session: object, router: _Router, clock: Callable[[], str],
                  stop: threading.Event) -> tuple[int, threading.Thread]:
    """
    Start a loopback grade server; return its port and (unstarted) thread.

    After each command the console's fish hook opens a TCP connection to this port over the
    shared loopback -- no bind mount, nothing visible in the container. We grade the current
    stage from the filesystem (the answers stay host-side; only pass/next-goal TEXT is sent
    back for the hook to print). An empty reply means nothing new passed. The thread runs while
    the foreground boot blocks the main thread.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((_GRADE_HOST, 0))
    srv.listen(8)
    srv.settimeout(_ACCEPT_POLL)
    port = srv.getsockname()[1]
    announce_io = Io(read=lambda _p: None, write=router.write, clock=clock)

    def loop() -> None:
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with conn, contextlib.suppress(OSError):
                conn.recv(64)                     # the tick payload (ignored)
                lines: list[str] = []
                router.to(lines.append)
                try:
                    while _advance_and_announce(session, announce_io):
                        pass
                finally:
                    router.to(_sink_noop)
                conn.sendall("".join(lines).encode())
        srv.close()

    return port, threading.Thread(target=loop, daemon=True)


def _interactive_console(runner: object, *, user: str | None = None, sudo: bool = True,
                         grade_port: int | None = None) -> None:
    """
    Boot the student's machine in the FOREGROUND, on the real terminal; return once it powers off.

    This is the documented way to get full, lossless console access to an nspawn container
    (systemd-nspawn(1): "to interactively start a container with full access to the container's
    console, invoke systemd-nspawn directly"). The terminal becomes the container's own console
    -- no `machinectl shell` dbus relay, which dropped fast keystrokes. The base image logs the
    console in (as HP_USER) to fish; typing `exit` powers the container off, so this returns and
    grading proceeds. `user` is the console login user (a task's `settings user`, default
    student); `grade_port` is the host loopback port the per-command grade hook connects to.
    """
    machine = f"{_MACHINE_PREFIX}{uuid.uuid4().hex[:_MACHINE_HEX]}"
    term = os.environ.get("TERM", _DEFAULT_TERM)
    argv = ["sudo", "systemd-nspawn", "-b", "-q", "-M", machine, f"--setenv=TERM={term}"]
    if user:
        argv.append(f"--setenv=HP_USER={user}")
    argv.append(f"--setenv=HP_SUDO={'on' if sudo else 'off'}")
    if grade_port is not None:
        argv.append(f"--setenv=HP_PORT={grade_port}")
    argv += ["-D", str(runner.rootfs)]
    subprocess.run(argv, check=False)


def _run_task(env: Home, ref: str, store: ImageStore, io: Io) -> int:
    """Boot the task console; grade after every command (live) and once more on exit."""
    # Unique workdir per run: a fresh overlay each session (no stale files -> no false
    # auto-pass) and no clash with a machine leaked by a previous run on a reused path.
    workdir = env.work / "run" / uuid.uuid4().hex
    router = _Router(io.write)                         # narrative + announces start on host stdout
    task_io = Io(read=io.read, write=router.write, clock=io.clock)
    session = run_task(ref, store, workdir, base=ensure_base_image(env, store),
                       student_id=_DEFAULT_STUDENT, nonce=uuid.uuid4().hex,
                       sink=router.write, sleep=time.sleep)
    stop = threading.Event()
    port, grader = _grade_server(session, router, io.clock, stop)
    try:
        session.enter()                    # greet + fire the first stage on_enter (host stdout)
        _announce_stage(session, task_io)
        task_io.write("(work in the shell; each command is checked; type `exit` to finish)\n")
        router.to(_sink_noop)              # during the boot only the grade thread emits (over the socket)
        grader.start()
        _interactive_console(session.student, user=session.meta.settings.user,
                             sudo=session.meta.settings.sudo, grade_port=port)
        stop.set()
        grader.join(timeout=_GRADER_JOIN)
        router.to(io.write)                # final sweep on host stdout (last command / handler stages)
        graded = current_stage(session.progress) is None
        while _advance_and_announce(session, task_io):
            graded = True
        if not graded and current_stage(session.progress) is not None:
            io.write("(no stage completed yet)\n")
    finally:
        stop.set()
        session.teardown()
    return 0


def _run_image(env: Home, ref: str, store: ImageStore) -> int:
    """Open a live shell in the booted image machine (inherited stdio), then tear down."""
    runner = run_image(ref, store, env.work / "run" / uuid.uuid4().hex,   # unique per run
                       base=ensure_base_image(env, store))
    try:
        _interactive_console(runner, user="root")   # a bare image is a raw root environment
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
