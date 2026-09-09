"""hashpass CLI: a Docker-style command-line front end over build/run/registry."""
import argparse
import base64
import contextlib
import getpass
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import termios
import threading
import time
import urllib.error
import urllib.parse
import uuid

try:
    import readline
except ImportError:                       # pragma: no cover - readline is optional
    readline = None
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from http import HTTPStatus
from pathlib import Path

from hashpass.build import build, run_image
from hashpass.image.base import _base_version_current, build_base
from hashpass.imagestore.store import ImageStore
from hashpass.progress import current_stage
from hashpass.recipe.model import CopyStep, Recipe, image_ref, is_task
from hashpass.recipe.parse import load_recipe
from hashpass.registry.config import load_config
from hashpass.registry.creds import CredentialCache
from hashpass.registry.passwords import UserStore, WeakPasswordError, validate_password
from hashpass.registry.refs import split_ref
from hashpass.registry.remote import RemoteRegistry
from hashpass.registry.server import make_server
from hashpass.registry.token import token_user
from hashpass.taskbuild import build_task
from hashpass.taskdigest import task_digest
from hashpass.taskrun import run_task
from hashpass.taskstore import task_dir
from hashpass.version import check_and_update

_ENV_HOME = "HASHPASS_HOME"
_HOME_DIRNAME = ".hashpass"
_IMAGES_DIRNAME = "images"
_BASE_DIRNAME = "base"
_BASE_TARNAME = "rootfs.tar"
_CREDS_NAME = "creds.json"
_WORK_DIRNAME = "work"
_REGISTRY_DIRNAME = "registry"     # local registry service data: store/, users.json, secret
_ENV_REGISTRY = "HASHPASS_REGISTRY"
_ENV_POOL = "HASHPASS_POOL"          # student: the pool URL to register/login/pull against
_POOL_NAME = "pool.json"             # student: saved {url, user}
# The local registry service. LOCALHOST ONLY -- images are pushed here, never to a real remote
# (no 185.x). A fixed URL keeps the login token cache stable across invocations.
_DEFAULT_REGISTRY = "http://127.0.0.1:8080"
_REGISTRY_START_TRIES = 50   # poll the auto-started service ~5s (50 x 0.1s) before giving up
_BASE_IMAGE = "debian:trixie-slim"  # slim boots + runs machinectl-shell commands reliably;
# full debian:trixie breaks command execution in the booted machine (and adds no ps/systemd).
_BASE_NAME = "debian"
_BASE_VERSION = "trixie"
_DEFAULT_STUDENT = "local"
_STOP_WORDS = frozenset({"exit", "quit"})
_COL_GAP = "  "
_HEADER = ("Образ", "Тип")
_KIND_RU = {"task": "задание", "image": "образ"}   # display labels; the stored kind stays task/image


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

    @property
    def registry(self) -> Path:
        return self.root / _REGISTRY_DIRNAME


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


def ensure_base_tar(dest: Path) -> Path:
    """
    Ensure the base rootfs tarball exists. It is provided out-of-band, not built by hashpass.

    Preparing a Debian rootfs is a rare, one-time, manual step (e.g. `docker export
    debian:trixie-slim -o rootfs.tar` on some machine, or debootstrap); hashpass itself has no
    build-time dependency on docker. If the tarball is missing, explain how to supply it.
    """
    if dest.exists():
        return dest
    msg = (f"базовый rootfs не найден: {dest}\n"
           f"положите туда тарбол ФС Debian — готовится один раз вручную, например:\n"
           f"  docker export {_BASE_IMAGE} -o {dest}\n"
           f"(или debootstrap). hashpass его сам не строит.")
    raise RuntimeError(msg)


def ensure_base_image(env: Home, store: ImageStore) -> Path:
    """
    Ensure the single base image `debian:trixie` exists in the store; build it once.

    Takes the provided Debian rootfs tarball (see ensure_base_tar), bakes it bootable +
    interactive (systemd, procps, fish, runtime) via build_base, and stores it as the parentless
    `debian:trixie` image that every build/run stacks on. Returns the stored base layer directory.
    """
    ref = f"{_BASE_NAME}:{_BASE_VERSION}"
    with contextlib.suppress(KeyError):
        layer = store.get(ref).layer
        if _base_layer_current(layer):
            return layer
        # else: a STALE stored base (e.g. built before the runtime filled /etc/hosts) -- rebuild it.
    ensure_base_tar(env.base_tar)
    built = build_base(env.work / "base-build", from_tar=env.base_tar)
    store.save(_BASE_NAME, _BASE_VERSION, built, (), sudo=True)  # root-owned rootfs -> sudo rsync
    return store.get(ref).layer


def _base_layer_current(layer: Path) -> bool:
    """
    Whether a stored base layer was built by the CURRENT runtime (matching version stamp).

    The runtime tree bakes an `/etc/hp-base-version` stamp; when the runtime changes (new base
    fixes, e.g. the /dev/ptmx fix) the stamp is bumped, so a stored base with an older/missing
    stamp is stale and rebuilt once on the next build/run.
    """
    return _base_version_current(layer)


def _kind(store: ImageStore, ref: str) -> str:
    """Classify a stored ref as a task (has a task/ artifacts dir) or a bare image."""
    return "task" if (store.get(ref).layer.parent / "task").exists() else "image"


def format_image_rows(rows: list[tuple[str, str]]) -> str:
    """Format (ref, kind) rows as a Docker-like two-column table (header always emitted)."""
    width = max((len(ref) for ref, _ in rows), default=0)
    width = max(width, len(_HEADER[0]))
    lines = [f"{_HEADER[0]:<{width}}{_COL_GAP}{_HEADER[1]}"]
    lines += [f"{ref:<{width}}{_COL_GAP}{_KIND_RU.get(kind, kind)}" for ref, kind in rows]
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
             write: Callable[[str], object], clock: Callable[[], str]) -> None:  # noqa: ARG001
    """
    Drive one interactive task session: prompt, feed, advance.

    `read(prompt)` returns the next student line (None/EOF or a stop word ends the loop); each
    line is fed with a `clock()` timestamp. There are NO forced pass/complete phrases -- progress
    shows in the prompt (`[stage N/M]`) and all narrative (say/show/voice/hint/on_pass) comes from
    the session's own Renderer sink. `write` is kept for interface symmetry with the CLI wiring.
    """
    session.enter()
    while current_stage(session.progress) is not None:
        line = read(_stage_prompt(session))
        if line is None or line.strip() in _STOP_WORDS:
            break
        session.feed(line, ts=clock())   # advancement shows as the next stage prompt; no forced phrase


def _progress(msg: str) -> None:
    """Print a live build-progress line (flushed so it shows as the build runs)."""
    sys.stdout.write("\x1b[2m  \u2502\x1b[0m " + msg.strip() + "\n")
    sys.stdout.flush()


def resolve_ref(recipe: Recipe, tag: str | None, taskfile: Path) -> tuple[str, str]:
    """Resolve name:version: `-t` wins, else the recipe's `image` name, else the Taskfile's dir."""
    if tag:
        name, sep, version = tag.partition(":")
        return name, (version if sep else "latest")
    if recipe.name:
        return recipe.name, recipe.version
    return taskfile.resolve().parent.name, "latest"


def _rebase_paths(recipe: Recipe, base: Path) -> Recipe:
    """Resolve a recipe's host paths (copy sources, hidden, readme) relative to the Taskfile's dir."""
    def rel(p: str | None) -> str | None:
        return str(base / p) if p and not Path(p).is_absolute() else p
    steps = tuple(replace(s, src=rel(s.src)) if isinstance(s, CopyStep) else s
                  for s in recipe.steps)
    return replace(recipe, steps=steps, hidden=rel(recipe.hidden), readme=rel(recipe.readme))


def cmd_build(env: Home, taskfile: str, tag: str | None = None, io: Io | None = None) -> int:
    """Build an image or a task from a Taskfile, under the owner's namespace (login required)."""
    io = io or _default_io()
    taskfile_path = Path(taskfile)
    recipe = load_recipe(taskfile_path)
    recipe = _rebase_paths(recipe, taskfile_path.resolve().parent)   # paths relative to the Taskfile
    name, version = resolve_ref(recipe, tag, taskfile_path)
    user = _require_login(env, io)                       # image creation requires a login
    recipe = replace(recipe, name=_namespace_name(name, user), version=version)
    store = ImageStore(env.images)
    base = ensure_base_image(env, store)
    ref = image_ref(recipe)
    task = is_task(recipe)
    sys.stdout.write(f"\x1b[1m▸ Собираю {ref}\x1b[0m\n")
    if task:
        build_task(recipe, store, base=base, workdir=env.work / "build", progress=_progress)
        kind = "задание"
    else:
        build(recipe, store, base=base, workdir=env.work / "build", progress=_progress)
        kind = "образ"
    sys.stdout.write(f"\x1b[32m✓ собрано\x1b[0m: {ref} ({kind})\n")
    store.set_taskfile_path(ref, str(taskfile_path.resolve()))   # push attaches it to the card later
    if task:
        # The registry blob carries an image's layer, not a task's hidden grader -- keep tasks local.
        io.write("\x1b[2m  задание сохранено локально (на сервис отправляются образы)\x1b[0m\n")
    else:
        _push_image(env, store, ref, io)
    return 0


def _announce_stage(session: object, io: Io) -> None:
    """Print the current stage goal (no number: the student does not know the count)."""
    stage = current_stage(session.progress)
    if stage is None:
        return
    io.write(f"\n\u2500\u2500  {session.meta.stages[stage].message}\n")


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
    if current_stage(session.progress) is None:
        session.fire_outro()   # completion/acceptance wording is the author's (voice bye / outro)
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
_MAX_REQ = 1 << 20         # cap a console request (hello / cmd <base64>) at 1 MiB


def _sink_noop(_text: str) -> None:
    """Swallow output -- a no-op sink used while nothing should reach the terminal."""


def _no_pause() -> None:
    """Pager pause used off a console request: do nothing."""


class _Router:
    """A write sink whose destination can be swapped -- host stdout, or a per-command buffer."""

    def __init__(self, target: Callable[[str], object]) -> None:
        self._target = target

    def write(self, text: str) -> object:
        return self._target(text)

    def to(self, target: Callable[[str], object]) -> None:
        self._target = target


def _recv_request(conn: socket.socket) -> str:
    """Read one newline-terminated console request line (`hello` or `cmd <base64>`)."""
    buf = b""
    while b"\n" not in buf and len(buf) < _MAX_REQ:
        chunk = conn.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf.split(b"\n", 1)[0].decode("utf-8", "replace")


def _render_intro(session: object, readme: str | None, io: Io) -> None:
    """Open the session INSIDE the console: voice hello, the top-level intro, readme, first goal."""
    session.enter()                          # voice hello (once) + stage 1 on_enter (via the sink)
    session.fire_intro()                     # top-level `say`/`read`/`exec` before the stages
    if readme:
        session.read_text(readme)            # markdown, paged (Enter), even reveal
    _announce_stage(session, io)
    io.write("(работайте в терминале — проверка после каждой команды; exit — завершить)\n")


# Escape sequences + stray control bytes, for cleaning a recorded terminal (script(1)) delta.
# OSC first (fish's semantic-prompt / title sequences, ESC ] ... BEL|ST) so the whole run goes,
# not just its ESC prefix; then CSI; then other 2-char escapes; then stray controls (keep \n \t).
_ANSI_RE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"      # OSC ... BEL or ST
    r"|\x1b\[[0-9;?]*[ -/]*[@-~]"             # CSI
    r"|\x1b[ -/]+[0-~]"                        # nF escapes incl. charset designation (ESC ( B) -- fish emits these
    r"|\x1b[@-Z\\-_]"                          # other 2-char escapes
    r"|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]",     # stray control bytes
)


def _strip_terminal(text: str) -> str:
    """Reduce a recorded-terminal (script(1)) delta to plain text."""
    # CRLF -> LF, then DROP a lone CR (cursor-return, not a newline): fish prints output as
    # `\r3\r\n`, and turning the leading CR into a newline left "\n3\n" -- a spurious blank line
    # that broke strict output grading. Dropping it yields the clean "3\n".
    text = text.replace("\r\n", "\n").replace("\r", "")
    return _ANSI_RE.sub("", text)


# fish marks command output with OSC 133 semantic prompts: ;C = output starts, ;D = output done.
_OSC133_C = re.compile(r"\x1b\]133;C[^\x07\x1b]*(?:\x07|\x1b\\)")
_OSC133_D = re.compile(r"\x1b\]133;D")


def _extract_output(delta: str) -> str:
    """
    Isolate a command's clean stdout from a recorded-terminal delta.

    fish emits OSC 133 semantic marks around each command's output (;C when it starts running,
    ;D when it finishes); the text between the LAST ;C and the next ;D is exactly that command's
    output, with the prompt + echoed command line excluded. That makes output grading STRICT (the
    student's actual output, not the surrounding console noise). If the marks are absent (older
    shell), fall back to the whole cleaned delta.
    """
    starts = list(_OSC133_C.finditer(delta))
    if not starts:
        return _strip_terminal(delta)
    begin = starts[-1].end()
    end = _OSC133_D.search(delta, begin)
    return _strip_terminal(delta[begin:end.start()] if end else delta[begin:])


def _parse_cmd_request(req: str) -> tuple[str, str]:
    """Decode a `cmd <command-b64> [<output-b64>]` request into (command, clean stdout)."""
    parts = req[4:].split(" ", 1)
    command = base64.b64decode(parts[0]).decode("utf-8", "replace")
    output = ""
    if len(parts) > 1 and parts[1]:
        output = _extract_output(base64.b64decode(parts[1]).decode("utf-8", "replace"))
    return command, output


def _policy_reply(session: object) -> str:
    """Return the current stage's command policy as `<allow>;<deny>;<neutral>` (comma-joined)."""
    stage = current_stage(session.progress)
    if stage is None:
        return ""
    sm = session.meta.stages[stage]
    return f"{','.join(sm.allow)};{','.join(sm.deny)};{','.join(sm.neutral)}\n"


def _render_observe(session: object, command: str, output: str, io: Io) -> None:
    """React/grade/hint on one console command (+ its captured output), then announce a pass."""
    res = session.observe(command, ts=io.clock(), output=output)  # react + grade + hints + on_pass
    if not res.advanced:
        return
    if current_stage(session.progress) is None:
        # Completion/acceptance wording is entirely the author's (`on pass`, `voice bye`, outro).
        # Keys stay host-side (`res.local_key`), compared under the hood -- nothing on-screen.
        session.fire_outro()                 # top-level `say`/`read`/`exec` after the last stage
    else:
        session.enter()                      # next stage's on_enter
        _announce_stage(session, io)


def _grade_server(session: object, router: _Router, clock: Callable[[], str],
                  stop: threading.Event, readme: str | None) -> tuple[int, threading.Thread]:
    """
    Start a loopback grade server; return its port and (unstarted) thread.

    The console (over the container's shared loopback, via bash's /dev/tcp -- no mount, nothing
    visible) connects at startup (`hello`) and after every command (`cmd <base64>`). The whole
    interaction runs HOST-side -- greet, react, grade the filesystem, fire hints and on_pass --
    and only the TEXT to print is sent back, so answers/graders never enter the container. It all
    renders live IN the console. The thread runs while the foreground boot blocks the main thread.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((_GRADE_HOST, 0))
    srv.listen(8)
    srv.settimeout(_ACCEPT_POLL)
    port = srv.getsockname()[1]

    def loop() -> None:
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with conn, contextlib.suppress(OSError):
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)   # per-char, no Nagle
                _handle_request(conn, _recv_request(conn),
                                session=session, router=router, readme=readme, clock=clock)
        srv.close()

    return port, threading.Thread(target=loop, daemon=True)


def _handle_request(conn: socket.socket, req: str, *, session: object,  # noqa: PLR0913
                    router: _Router, readme: str | None, clock: Callable[[], str]) -> None:
    """Serve one console request: `policy` (raw reply), else `hello`/`cmd` rendered to the socket."""
    if req.startswith("policy"):
        # The console PULLS the current stage's command policy before running each command, so it
        # can block a disallowed command locally (see runtime config.fish). Raw reply, no render.
        with contextlib.suppress(OSError):
            conn.sendall(_policy_reply(session).encode())
        return

    # Stream rendered output STRAIGHT to the socket so the typewriter's pacing types out live;
    # buffering here and sending at once would lose the effect.
    def sink(text: str) -> None:
        with contextlib.suppress(OSError):
            conn.sendall(text.encode())

    def pause() -> None:
        # page break: send the 0x01 control byte and block until the console reports Enter.
        with contextlib.suppress(OSError):
            conn.sendall(b"\x01")
            conn.recv(16)

    io = Io(read=lambda _p: None, write=router.write, clock=clock)
    router.to(sink)
    session.pause = pause
    try:
        if req.startswith("hello"):
            _render_intro(session, readme, io)
        elif req.startswith("cmd "):
            with contextlib.suppress(Exception):
                _render_observe(session, *_parse_cmd_request(req), io)
    finally:
        router.to(_sink_noop)
        session.pause = _no_pause


def _reap_stale_machines() -> None:
    """
    Terminate leftover hashpass containers (hp-*) from interrupted prior runs, reclaiming ptys.

    A clean run powers its machine off; an interrupted one (Ctrl-C, a closed terminal) leaks it,
    and every leaked machine holds ptys against kernel.pty.max. Enough of them and script(1) (live
    output capture) -- or even a fresh boot -- fails with "No space left on device". Reaping our
    OWN orphaned machines before a boot reclaims those ptys. Assumes one hashpass run at a time.
    """
    with contextlib.suppress(Exception):
        out = subprocess.run(["machinectl", "list", "--no-legend"],
                             capture_output=True, text=True, check=False).stdout
        for line in out.splitlines():
            parts = line.split()
            if parts and parts[0].startswith(_MACHINE_PREFIX):
                subprocess.run(["sudo", "machinectl", "terminate", parts[0]],
                               check=False, capture_output=True)


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
    _reap_stale_machines()             # reclaim ptys from any interrupted prior runs
    try:
        saved_tty = termios.tcgetattr(sys.stdin.fileno())
    except (termios.error, ValueError, OSError):
        saved_tty = None
    try:
        subprocess.run(argv, check=False)
    finally:
        # SAFETY: nspawn leaves the terminal in raw mode and an interrupted/failed boot would
        # otherwise leave the shell "hung"; always restore it. And terminate the machine -- a
        # clean poweroff already removed it (no-op), but an interrupted boot would leak its ptys.
        with contextlib.suppress(Exception):
            subprocess.run(["sudo", "machinectl", "terminate", machine],
                           check=False, capture_output=True)
        if saved_tty is not None:
            with contextlib.suppress(termios.error, ValueError, OSError):
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved_tty)


def _run_task(env: Home, ref: str, store: ImageStore, io: Io, *,  # noqa: PLR0913
              student_id: str = _DEFAULT_STUDENT,
              on_complete: Callable[[bool], None] | None = None) -> int:
    """Boot the task console; grade live, then report whether every stage passed via on_complete."""
    # Unique workdir per run: a fresh overlay each session (no stale files -> no false
    # auto-pass) and no clash with a machine leaked by a previous run on a reused path.
    workdir = env.work / "run" / uuid.uuid4().hex
    router = _Router(io.write)                         # narrative + announces start on host stdout
    task_io = Io(read=io.read, write=router.write, clock=io.clock)
    session = run_task(ref, store, workdir, base=ensure_base_image(env, store),
                       student_id=student_id, nonce=uuid.uuid4().hex,
                       sink=router.write, sleep=time.sleep)
    stop = threading.Event()
    port, grader = _grade_server(session, router, io.clock, stop, session.meta.readme)
    completed = False
    try:
        # The whole interaction (greeting, per-command react/grade/hints/on_pass) runs live IN
        # the console over the grade socket -- so nothing is printed before the boot, where the
        # container's own boot output would scroll it away.
        router.to(_sink_noop)
        grader.start()
        _interactive_console(session.student, user=session.meta.settings.user,
                             sudo=session.meta.settings.sudo, grade_port=port)
        stop.set()
        grader.join(timeout=_GRADER_JOIN)
        router.to(io.write)                # final sweep on host stdout (any stage / voice bye at exit)
        while _advance_and_announce(session, task_io):
            pass
        completed = current_stage(session.progress) is None   # every stage passed
    finally:
        stop.set()
        session.teardown()
    if on_complete is not None:
        on_complete(completed)
    return 0


def _prompt_save_as(default: str) -> str | None:
    """
    Ask where to save the edited image, with `default` (the current ref) pre-filled + editable.

    Returns the chosen ref, or None to NOT save (an empty answer, EOF, or no terminal to ask on).
    """
    try:
        is_tty = sys.stdin.isatty()
    except (OSError, ValueError):
        is_tty = False
    if not is_tty:
        return None
    if readline is not None:
        readline.set_startup_hook(lambda: readline.insert_text(default))
    try:
        answer = input("\nСохранить образ как (пусто — не сохранять): ").strip()
    except EOFError:
        answer = ""
    finally:
        if readline is not None:
            readline.set_startup_hook()
    return answer or None


def _commit_image_edits(env: Home, runner: object, store: ImageStore, ref: str, io: Io) -> None:
    """Save the console's edits back into an image (its layer + overlay upper), namespaced + pushed."""
    upper = runner.rootfs_upper
    try:
        changed = any(upper.iterdir())
    except OSError:
        changed = False
    if not changed:
        io.write("Изменений нет.\n")
        return
    user = _require_login(env, io)   # image creation requires a login (asked once, then cached)
    rname, _, rversion = ref.partition(":")
    default = f"{_namespace_name(rname, user)}:{rversion or 'latest'}"
    target = _prompt_save_as(default)
    if not target:
        io.write("Изменения не сохранены.\n")
        return
    name, _, version = target.partition(":")
    version = version or "latest"
    stored = store.get(ref)
    tmp = runner.rootfs.parent / "commit"
    tmp.mkdir(parents=True, exist_ok=True)
    # new layer = the image's current delta with the edited overlay upper applied on top
    # (rsync preserves overlay whiteouts, so deletions carry over too).
    subprocess.run(["sudo", "rsync", "-a", "--delete", str(stored.layer) + "/", str(tmp) + "/"], check=True)
    subprocess.run(["sudo", "rsync", "-a", str(upper) + "/", str(tmp) + "/"], check=True)
    store.save(name, version, tmp, stored.parents, sudo=True)
    io.write(f"\x1b[32m✓ сохранено\x1b[0m: {name}:{version}\n")
    _push_image(env, store, f"{name}:{version}", io)


def _run_image(env: Home, ref: str, store: ImageStore, io: Io) -> int:
    """Edit a bare image live: open a root console, then commit any changes back to the image."""
    runner = run_image(ref, store, env.work / "run" / uuid.uuid4().hex,   # unique per run
                       base=ensure_base_image(env, store))
    try:
        _interactive_console(runner, user="root")   # a raw root console -- edit the image freely
        _commit_image_edits(env, runner, store, ref, io)
    finally:
        runner.teardown()
    return 0


def cmd_run(env: Home, ref: str, io: Io | None = None, *,
            student_id: str = _DEFAULT_STUDENT,
            on_complete: Callable[[bool], None] | None = None) -> int:
    """Run a task (interactive student session) or a bare image (interactive shell)."""
    io = io or _default_io()
    store = ImageStore(env.images)
    try:
        stored = store.get(ref)
    except KeyError:
        io.write(f"нет такого образа: {ref}\n")
        return 1
    if (stored.layer.parent / "task").exists():
        return _run_task(env, ref, store, io, student_id=student_id, on_complete=on_complete)
    return _run_image(env, ref, store, io)


def _local_registry_url() -> str:
    """Return the local registry service URL (localhost only; overridable via HASHPASS_REGISTRY)."""
    return os.environ.get(_ENV_REGISTRY, _DEFAULT_REGISTRY)


def _registry_host_port(url: str) -> tuple[str, int]:
    """Split a registry URL into (host, port), defaulting the port to 80."""
    parsed = urllib.parse.urlsplit(url)
    return parsed.hostname or "127.0.0.1", parsed.port or 80


def _registry_reachable(url: str) -> bool:
    """Return whether the local registry service is accepting connections."""
    host, port = _registry_host_port(url)
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _registry_secret(env: Home) -> bytes:
    """Load (or create once) the persistent HMAC secret for the local registry service."""
    path = env.registry / "secret"
    if path.exists():
        return path.read_bytes()
    env.registry.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(32)
    path.write_bytes(secret)
    path.chmod(0o600)
    return secret


def _ensure_registry(env: Home, io: Io) -> str:
    """Return the local registry URL, auto-starting the service in the background if it is down."""
    url = _local_registry_url()
    if _registry_reachable(url):
        return url
    env.registry.mkdir(parents=True, exist_ok=True)
    with (env.registry / "serve.log").open("ab") as log:
        subprocess.Popen(  # detached: outlives this CLI process and keeps serving
            [sys.executable, "-m", "hashengine", "serve"],
            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True, env={**os.environ, _ENV_HOME: str(env.root)},
        )
    for _ in range(_REGISTRY_START_TRIES):
        if _registry_reachable(url):
            io.write(f"\x1b[2m  запущен локальный реестр: {url}\x1b[0m\n")
            return url
        time.sleep(0.1)
    msg = f"не удалось запустить локальный реестр ({url}); см. {env.registry / 'serve.log'}"
    raise RuntimeError(msg)


def _require_login(env: Home, io: Io) -> str:
    """
    Ensure a logged-in user for image creation and return the login (asked once, then cached).

    A valid cached token -> its user, no prompt. Otherwise the service is started if needed, the
    user is asked for a login + password (registered locally on first use), authenticated, and the
    token is cached until it expires.
    """
    url = _local_registry_url()
    cache = CredentialCache(env.creds)
    token = cache.cached_token(url, now=time.time())
    if token is not None and (user := token_user(token)):
        return user
    _ensure_registry(env, io)
    user = (io.read("логин: ") or "").strip()
    if not user:
        msg = "логин обязателен для создания образа"
        raise RuntimeError(msg)
    password = getpass.getpass("пароль: ")
    users = UserStore(env.registry / "users.json")
    if not users.has(user):
        # first use of this login here -> register it locally as the machine owner (admin)
        users.add(user, password, role="admin")
    RemoteRegistry(url, cache=cache).login(user, password)
    io.write(f"\x1b[32m✓ вход выполнен\x1b[0m: {user}\n")
    return user


def _namespace_name(name: str, user: str) -> str:
    """Prefix a name with the owner's login (idempotent: a leading owner segment is replaced)."""
    return f"{user}/{name.rsplit('/', 1)[-1]}"


def _push_image(env: Home, store: ImageStore, ref: str, io: Io) -> None:
    """Push a saved image (and its `from` closure) to the local registry service; warn on failure."""
    url = _ensure_registry(env, io)
    cache = CredentialCache(env.creds)
    try:
        copied = RemoteRegistry(url, cache=cache).push(store, ref)
    except (urllib.error.URLError, ValueError, OSError) as exc:
        io.write(f"\x1b[33m⚠ не удалось отправить на сервис: {exc}\x1b[0m\n")
        return
    io.write(f"\x1b[36m↑ отправлено на сервис\x1b[0m: {ref} ({len(copied)} слой(ёв))\n")


def _seed_admin(users: UserStore, io: Io, *, reset: bool = False) -> None:
    """
    Ensure a pool admin: create one on an empty pool (or regenerate on `reset`); print once.

    Password comes from $HASHPASS_ADMIN_PASSWORD, else a freshly generated one that is printed
    a single time. `reset=True` (serve --reset-admin) regenerates it even on a non-empty pool —
    the operator's recovery when the admin password was lost.
    """
    admin_user = os.environ.get("HASHPASS_ADMIN", "admin")
    if users.all_users() and not reset:
        return
    admin_pw = os.environ.get("HASHPASS_ADMIN_PASSWORD")
    generated = admin_pw is None
    if generated:
        admin_pw = secrets.token_urlsafe(12)
    if users.has(admin_user):
        users.set_password(admin_user, admin_pw)
        io.write(f"\x1b[36m✓ пароль администратора перегенерирован: {admin_user}\x1b[0m\n")
    else:
        users.add(admin_user, admin_pw, role="admin", comment="pool administrator")
        io.write(f"\x1b[36m✓ создан администратор пула: {admin_user}\x1b[0m\n")
    if generated:
        io.write(f"\x1b[33m  пароль (сохраните — покажется один раз): {admin_pw}\x1b[0m\n")


def _local_ips() -> list[str]:
    """Best-effort non-loopback IPv4 addresses of this host (for the 0.0.0.0 entry hint)."""
    ips: set[str] = set()
    with contextlib.suppress(OSError):
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    with contextlib.suppress(OSError):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))   # sends nothing; just picks the outbound interface
            ips.add(probe.getsockname()[0])
        finally:
            probe.close()
    return sorted(ip for ip in ips if not ip.startswith("127."))


def _resolve_tls(env: Home, certfile: str | None, keyfile: str | None,
                 *, self_signed: bool) -> tuple[Path | None, Path | None]:
    """Return (cert, key) for HTTPS: explicit pair, else a self-signed one (openssl), else (None, None)."""
    if certfile and keyfile:
        return Path(certfile), Path(keyfile)
    if not self_signed:
        return None, None
    tls_dir = env.registry / "tls"
    cert, key = tls_dir / "cert.pem", tls_dir / "key.pem"
    if not (cert.exists() and key.exists()):
        tls_dir.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(   # fixed args; one-time self-signed cert
                ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                 "-out", str(cert), "-days", "3650", "-subj", "/CN=hashpass"],
                check=True, capture_output=True)
        except FileNotFoundError as exc:
            msg = "для --tls-self-signed нужен openssl (или задайте --tls-cert/--tls-key)"
            raise RuntimeError(msg) from exc
    return cert, key


def cmd_serve(env: Home, host: str | None = None, port: int | None = None, *,  # noqa: PLR0913
              certfile: str | None = None, keyfile: str | None = None,
              self_signed: bool = False, reset_admin: bool = False) -> int:
    """
    Run the pool (registry + web); bind the port before seeding an admin.

    A busy port then fails cleanly without leaving a spurious admin. Host/port come from the args,
    else $HASHPASS_REGISTRY, else 127.0.0.1:8080 (use --host 0.0.0.0 to expose the pool). With
    --tls-cert/--tls-key or --tls-self-signed the pool speaks HTTPS.
    """
    default_host, default_port = _registry_host_port(_local_registry_url())
    bind_host = host if host is not None else default_host
    bind_port = port if port is not None else default_port
    cert, key = _resolve_tls(env, certfile, keyfile, self_signed=self_signed)
    store = ImageStore(env.registry / "store")
    users = UserStore(env.registry / "users.json")
    config_path = env.registry / "config.json"
    server = make_server(store, users, _registry_secret(env), host=bind_host, port=bind_port,
                         config=load_config(config_path), config_path=config_path,
                         catalog_path=env.registry / "catalog.json",
                         progress_path=env.registry / "progress",
                         certfile=cert, keyfile=key)   # binds now; a busy port raises here
    _seed_admin(users, _default_io(), reset=reset_admin)   # only after the port bound successfully

    def _stop(*_a: object) -> None:
        raise KeyboardInterrupt   # SIGTERM -> clean shutdown, same path as Ctrl-C

    with contextlib.suppress(ValueError):   # signals are only settable in the main thread
        signal.signal(signal.SIGTERM, _stop)
    scheme = "https" if cert is not None else "http"
    bound_host, bound_port = server.server_address
    if bound_host in ("0.0.0.0", "::"):   # noqa: S104  (operator explicitly exposed the pool)
        sys.stdout.write(f"пул слушает все интерфейсы ({scheme}, порт {bound_port}). Входы:\n")
        sys.stdout.write(f"  {scheme}://127.0.0.1:{bound_port}   (локально)\n")
        for ip in _local_ips():
            sys.stdout.write(f"  {scheme}://{ip}:{bound_port}\n")
        sys.stdout.write("Ctrl-C — остановить\n")
    else:
        sys.stdout.write(f"пул на {scheme}://{bound_host}:{bound_port} (Ctrl-C — остановить)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stdout.write("\nостановлен\n")
    finally:
        server.server_close()   # release the listening socket promptly on exit
    return 0


def _prompt_registry(env: Home, registry: str | None, io: Io) -> str:
    """Resolve the registry URL: explicit arg → saved (pool.json/$HASHPASS_POOL) → prompt once."""
    url = _pool_url(env, registry) or (io.read("Адрес реестра/пула (URL): ") or "").strip()
    if not url:
        msg = "не задан адрес реестра (укажите URL или задайте один раз через login)"
        raise RuntimeError(msg)
    return url


def _ensure_registry_login(env: Home, registry: str | None, io: Io) -> str:
    """Resolve the registry and ensure a cached token, prompting for login inline if there is none."""
    url = _prompt_registry(env, registry, io)
    if _pool_token(env, url) is None:
        user = (io.read("логин: ") or "").strip()
        if not user:
            msg = "логин обязателен"
            raise RuntimeError(msg)
        try:
            RemoteRegistry(url, cache=CredentialCache(env.creds)).login(user, getpass.getpass("пароль: "))
        except urllib.error.HTTPError as exc:
            if exc.code == HTTPStatus.UNAUTHORIZED:
                msg = "неверный логин или пароль"
                raise RuntimeError(msg) from exc
            raise
        save_pool(env, url, user)
        io.write(f"\x1b[32m✓ вход выполнен\x1b[0m: {user}\n")
    return url


def cmd_login(env: Home, registry: str | None = None, io: Io | None = None) -> int:
    """Log in to a registry/pool: prompts login + password inline; caches the token, saves the URL."""
    io = io or _default_io()
    url = _prompt_registry(env, registry, io)
    user = (io.read("логин: ") or "").strip()
    if not user:
        msg = "логин обязателен"
        raise RuntimeError(msg)
    try:
        RemoteRegistry(url, cache=CredentialCache(env.creds)).login(user, getpass.getpass("пароль: "))
    except urllib.error.HTTPError as exc:
        if exc.code == HTTPStatus.UNAUTHORIZED:
            io.write("неверный логин или пароль\n")
            return 1
        raise
    except urllib.error.URLError as exc:
        io.write(f"вход не выполнен: {exc}\n")
        return 1
    save_pool(env, url, user)
    io.write(f"\x1b[32m✓ вход выполнен\x1b[0m: {user}\n")
    return 0


def _attach_taskfile(client: RemoteRegistry, store: ImageStore, ref: str, io: Io) -> None:
    """On push, upload the Taskfile the image remembers (so its solutions/interactivity are on the pool)."""
    try:
        taskfile = store.get(ref).taskfile_path
    except KeyError:
        return
    path = Path(taskfile) if taskfile else None
    if path is None or not path.is_file():
        io.write("\x1b[2mTaskfile не найден — можете приложить файлы вручную в карточке образа\x1b[0m\n")
        return
    name, version = split_ref(ref)
    try:
        client.push_attachment(name, version, path.name, path.read_bytes(), taskfile=True)
    except (urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
        io.write(f"\x1b[33m⚠ не удалось прикрепить Taskfile: {exc}\x1b[0m\n")
        return
    io.write(f"\x1b[36m↑ прикреплён Taskfile\x1b[0m: {path.name}\n")


def cmd_push(env: Home, ref: str, registry: str | None = None, *,
             publish: bool = False, io: Io | None = None) -> int:
    """
    Push a ref (+ its `from` closure); with `publish`, also add it to the catalog (auto-numbered).

    Resolves the registry (explicit → saved) and logs in inline if there is no cached token.
    """
    io = io or _default_io()
    url = _ensure_registry_login(env, registry, io)
    store = ImageStore(env.images)
    client = RemoteRegistry(url, cache=CredentialCache(env.creds))
    copied = client.push(store, ref)
    sys.stdout.write(f"отправлено {ref} (слоёв: {len(copied)})\n")
    _attach_taskfile(client, store, ref, io)
    if publish:
        tdir = task_dir(ref, store)
        if not tdir.exists():
            msg = f"{ref} — не задание (нет артефактов task/); публиковать нечего"
            raise ValueError(msg)
        name, version = split_ref(ref)
        client.push_task(tdir, name, version, publish=True)
        sys.stdout.write(f"опубликовано в каталог: {ref}\n")
    return 0


def cmd_pull(env: Home, ref: str, registry: str | None = None, io: Io | None = None) -> int:
    """Pull a ref and its `from` closure from a registry (anonymous); registry saved/optional."""
    io = io or _default_io()
    url = _prompt_registry(env, registry, io)
    store = ImageStore(env.images)
    copied = RemoteRegistry(url).pull(ref, store)
    sys.stdout.write(f"подтянуто {ref} (слоёв: {len(copied)})\n")
    return 0


def cmd_remote_images(env: Home, registry: str | None = None, io: Io | None = None) -> int:
    """List the images/tasks the pool holds (ref, kind, catalog number); registry saved/optional."""
    io = io or _default_io()
    url = _ensure_registry_login(env, registry, io)
    rows = RemoteRegistry(url, cache=CredentialCache(env.creds)).pool_images()
    lines = [f"{'Образ':<30}{_COL_GAP}{'Тип':<8}{_COL_GAP}№"]
    lines += [f"{r['ref']!s:<30}{_COL_GAP}{_KIND_RU.get(str(r['kind']), str(r['kind'])):<8}{_COL_GAP}"
              f"{r['number'] if r.get('number') is not None else ''}" for r in rows]
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


# --- student pool client: identity, parallel pull, catalog listing --------------------

def _pool_path(env: Home) -> Path:
    return env.root / _POOL_NAME


def load_pool(env: Home) -> dict[str, str]:
    """Read the saved pool config ({url, user}); {} if absent or unreadable."""
    path = _pool_path(env)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_pool(env: Home, url: str, user: str) -> None:
    """Persist the pool URL + login so later runs need no re-typing."""
    env.root.mkdir(parents=True, exist_ok=True)
    _pool_path(env).write_text(json.dumps({"url": url, "user": user}, indent=2), encoding="utf-8")


def _pool_url(env: Home, explicit: str | None = None) -> str | None:
    """Resolve the pool URL: explicit arg -> $HASHPASS_POOL -> saved pool.json."""
    return explicit or os.environ.get(_ENV_POOL) or load_pool(env).get("url") or None


def _pool_token(env: Home, url: str) -> str | None:
    return CredentialCache(env.creds).cached_token(url, now=time.time())


def cmd_config_pool(env: Home, url: str | None = None, io: Io | None = None) -> int:
    """
    Show or set the saved pool address (`hashpass config pool [URL]`).

    Without URL, print the current pool. With URL, save it to pool.json so later runs use it;
    the scheme is optional (the client tries https then http) — e.g. `config pool 1.2.3.4:8080`.
    """
    io = io or _default_io()
    if url is None:
        current = _pool_url(env)
        io.write(f"текущий пул: {current}\n" if current else "пул не задан\n")
        return 0
    url = url.strip()
    if not url:
        msg = "укажите адрес пула, например: hashpass config pool 1.2.3.4:8080"
        raise RuntimeError(msg)
    pool = load_pool(env)
    keep_user = str(pool.get("user", "")) if pool.get("url") == url else ""
    save_pool(env, url, keep_user)   # switching pools drops the stale login hint
    io.write(f"\x1b[32m✓ пул сохранён\x1b[0m: {url}\n")
    return 0


def _prompt_new_password(io: Io) -> str:
    """Prompt for a new password twice, enforcing the policy, until the two entries match."""
    io.write("пароль: не короче 8 символов, минимум одна буква, одна цифра и один спецсимвол\n")
    while True:
        pw = getpass.getpass("пароль: ")
        try:
            validate_password(pw)
        except WeakPasswordError as exc:
            io.write(f"{exc}\n")
            continue
        if getpass.getpass("повторите пароль: ") == pw:
            return pw
        io.write("пароли не совпадают, попробуйте снова\n")


def cmd_register(env: Home, pool_url: str | None = None, io: Io | None = None) -> int:
    """Register on the pool (group required; comment free-form); cache the token and save pool config."""
    io = io or _default_io()
    url = _pool_url(env, pool_url) or (io.read("Адрес пула (URL): ") or "").strip()
    if not url:
        msg = "не задан адрес пула (--pool или HASHPASS_POOL)"
        raise RuntimeError(msg)
    user = (io.read("логин: ") or "").strip()
    group = (io.read("группа (например ИУ7-31): ") or "").strip()
    comment = (io.read("комментарий (необязательно): ") or "").strip()
    if not user or not group:
        msg = "логин и группа обязательны для регистрации"
        raise RuntimeError(msg)
    password = _prompt_new_password(io)
    RemoteRegistry(url, cache=CredentialCache(env.creds)).register(user, password, group, comment)
    save_pool(env, url, user)
    io.write(f"\x1b[32m✓ регистрация выполнена\x1b[0m: {user}\n")
    return 0


def cmd_pool_login(env: Home, pool_url: str | None = None, io: Io | None = None) -> int:
    """Log in to the pool; cache the token and save the pool config."""
    io = io or _default_io()
    url = _pool_url(env, pool_url) or (io.read("Адрес пула (URL): ") or "").strip()
    if not url:
        msg = "не задан адрес пула (--pool или HASHPASS_POOL)"
        raise RuntimeError(msg)
    user = (io.read("логин: ") or "").strip()
    password = getpass.getpass("пароль: ")
    try:
        RemoteRegistry(url, cache=CredentialCache(env.creds)).login(user, password)
    except urllib.error.URLError as exc:
        io.write(f"вход не выполнен: {exc}\n")
        return 1
    save_pool(env, url, user)
    io.write(f"\x1b[32m✓ вход выполнен\x1b[0m: {user}\n")
    return 0


def _register_interactive(client: RemoteRegistry, user: str, io: Io) -> None:
    """Offer registration after a failed login: group + optional comment + confirmed password."""
    io.write(f"Пользователь «{user}» не найден или пароль неверный.\n")
    ans = (io.read("Зарегистрироваться с этим логином? [Enter — да, n — нет]: ") or "").strip().lower()
    if ans in ("n", "no", "нет"):
        msg = "вход отменён"
        raise RuntimeError(msg)
    group = (io.read("группа (например ИУ7-31): ") or "").strip()
    comment = (io.read("комментарий (необязательно): ") or "").strip()
    if not group:
        msg = "группа обязательна для регистрации"
        raise RuntimeError(msg)
    password = _prompt_new_password(io)
    try:
        client.register(user, password, group, comment)
    except urllib.error.HTTPError as exc:
        if exc.code == HTTPStatus.CONFLICT:
            msg = f"логин «{user}» уже занят — вход не удался из-за неверного пароля"
            raise RuntimeError(msg) from exc
        if exc.code == HTTPStatus.FORBIDDEN:
            msg = "регистрация на пуле закрыта — обратитесь к преподавателю"
            raise RuntimeError(msg) from exc
        raise
    io.write(f"\x1b[32m✓ регистрация выполнена\x1b[0m: {user}\n")


def _require_pool_identity(env: Home, io: Io) -> tuple[str, str]:
    """
    Return (url, user) for the pool.

    With a valid cached token, returns it silently. Otherwise asks for a login + password directly;
    if that login fails, offers registration in place (group + optional comment, password confirmed).
    """
    url = _pool_url(env)
    if url and (token := _pool_token(env, url)) and (user := token_user(token)):
        return url, user
    if not url:
        url = (io.read("Адрес пула (URL): ") or "").strip()
        if not url:
            msg = "не задан адрес пула (HASHPASS_POOL)"
            raise RuntimeError(msg)
    user = (io.read("логин: ") or "").strip()
    if not user:
        msg = "логин обязателен"
        raise RuntimeError(msg)
    client = RemoteRegistry(url, cache=CredentialCache(env.creds))
    try:
        client.login(user, getpass.getpass("пароль: "))
    except urllib.error.HTTPError as exc:
        if exc.code != HTTPStatus.UNAUTHORIZED:
            raise
        _register_interactive(client, user, io)   # unknown login / bad password -> offer sign-up
    else:
        io.write(f"\x1b[32m✓ вход выполнен\x1b[0m: {user}\n")
    save_pool(env, url, user)
    return url, user


def pull_new(env: Home, url: str, token: str, *, workers: int = 8) -> tuple[int, int]:
    """Pull catalog images (parallel) + changed task bundles; return (layers, tasks) fetched."""
    store = ImageStore(env.images)
    client = RemoteRegistry(url)
    entries = [e for e in client.catalog(token=token) if e.get("available", True)]  # skip locked
    layers = client.pull_many([str(e["ref"]) for e in entries], store, workers=workers)

    def _task(entry: dict[str, object]) -> str | None:
        ref = str(entry["ref"])
        tdir = task_dir(ref, store)
        if not tdir.exists() or task_digest(tdir) != entry.get("digest"):
            client.pull_task(ref, tdir, token=token)
            return ref
        return None

    tasks: list[str] = []
    if entries:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            tasks = [ref for ref in pool.map(_task, entries) if ref]
    return len(layers), len(tasks)


def _resolve_pool_ref(client: RemoteRegistry, token: str, arg: str) -> str:
    """Resolve a catalog number to its ref; pass a non-numeric arg through unchanged."""
    if arg.isdigit():
        entry = next((e for e in client.catalog(token=token) if e["number"] == int(arg)), None)
        if entry is None:
            msg = f"нет задания №{arg} в пуле"
            raise RuntimeError(msg)
        return str(entry["ref"])
    return arg


def cmd_pool_pull(env: Home, io: Io | None = None) -> int:
    """Refresh: ensure pool identity, then pull new/updated tasks in parallel."""
    io = io or _default_io()
    url, _user = _require_pool_identity(env, io)
    layers, tasks = pull_new(env, url, _pool_token(env, url) or "")
    io.write(f"подтянуто: слоёв {layers}, заданий {tasks}\n")
    return 0


def _solved_path(env: Home) -> Path:
    return env.root / "solved.json"


def load_solved(env: Home) -> dict[str, dict[str, object]]:
    """Read the local record of tasks solved on this machine ({ref: {...}}); {} if none."""
    path = _solved_path(env)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def mark_solved(env: Home, ref: str) -> None:
    """Record locally that `ref` was solved here (the console graded every stage passed)."""
    data = load_solved(env)
    data[ref] = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    env.root.mkdir(parents=True, exist_ok=True)
    _solved_path(env).write_text(json.dumps(data, indent=2), encoding="utf-8")


def pool_status(env: Home, url: str, token: str, user: str) -> list[dict[str, object]]:
    """
    Per available task: {number, title, ref, local, server}.

    `local` = solved on this machine (self-check); `server` = the pool's verdict ('passed'/'failed'/None).
    """
    client = RemoteRegistry(url)
    entries = client.catalog(token=token)
    try:
        mine = client.progress(token=token).get(user, {})
    except (urllib.error.URLError, RuntimeError):
        mine = {}   # offline: still show what was solved locally
    solved = load_solved(env)
    rows: list[dict[str, object]] = []
    for entry in entries:
        ref = str(entry["ref"])
        server = mine.get(ref, {}).get("status") if isinstance(mine.get(ref), dict) else None
        rows.append({"number": entry["number"], "title": ref,   # a task's name is its image ref
                     "ref": ref, "local": ref in solved, "server": server,
                     "available": entry.get("available", True),
                     "block": str(entry.get("block_name", ""))})
    return rows


def _status_badge(row: dict[str, object]) -> str:
    if not row.get("available", True):
        return "\x1b[2mнедоступно\x1b[0m"          # visible, but locked right now
    if row.get("server") == "passed":
        return "\x1b[32m★ зачтено\x1b[0m"
    if row.get("local"):
        return "\x1b[33m✓ решено\x1b[0m"
    return "\x1b[2m· не начато\x1b[0m"


def _render_pool_menu(rows: list[dict[str, object]], user: str) -> str:
    lines = [f"\x1b[1mВаши задания\x1b[0m ({user}):", ""]
    block = object()   # sentinel so the first block header always prints
    for r in rows:
        if r.get("block") != block:
            block = r.get("block")
            lock = "" if r.get("available", True) else "  \x1b[2m(закрыт)\x1b[0m"
            lines.append(f"\x1b[1m{block or 'Задания'}\x1b[0m{lock}" if block or lock else "Задания")
        lines.append(f"  {r['number']:>2}. [{_status_badge(r)}] {r['title']}")
    lines.append("")
    return "\n".join(lines)


def _next_number(rows: list[dict[str, object]], after: int) -> int | None:
    """Return the next task worth doing after `after` (first uncredited ahead, else first)."""
    todo = [r for r in rows if r.get("server") != "passed" and r.get("available", True)]
    ahead = [r for r in todo if int(r["number"]) > after]  # type: ignore[arg-type]
    pick = (ahead or todo)
    return int(pick[0]["number"]) if pick else None  # type: ignore[arg-type]


def _resync(env: Home, url: str, user: str, token: str, io: Io) -> None:
    """Self-check: re-submit tasks solved locally but not yet credited on the server."""
    client = RemoteRegistry(url)
    mine = client.progress(token=token).get(user, {})
    store = ImageStore(env.images)
    sent = 0
    for ref in load_solved(env):
        if isinstance(mine.get(ref), dict) and mine[ref].get("status") == "passed":
            continue
        tdir = task_dir(ref, store)
        if not tdir.exists():
            continue
        try:
            result = client.submit(ref, task_digest(tdir), passed=True, token=token)
        except (urllib.error.URLError, RuntimeError, ValueError):
            continue
        sent += result.get("status") == "passed"
    io.write(f"\x1b[36mсамопроверка: зачтено {sent}\x1b[0m\n")


def cmd_pool_home(env: Home, io: Io | None = None) -> int:
    """Student no-arg: a friendly menu — pull tasks, show status, pick one to run, offer the next."""
    io = io or _default_io()
    url, user = _require_pool_identity(env, io)
    token = _pool_token(env, url) or ""
    layers, tasks = pull_new(env, url, token)
    if layers or tasks:
        io.write(f"\x1b[2m↓ подтянуто: слоёв {layers}, заданий {tasks}\x1b[0m\n")
    while True:
        rows = pool_status(env, url, token, user)
        if not rows:
            io.write("в пуле пока нет доступных заданий\n")
            return 0
        io.write(_render_pool_menu(rows, user) + "\n")
        choice = (io.read("Номер задания (Enter — обновить, s — самопроверка, q — выход): ")
                  or "").strip().lower()
        if choice in ("q", "quit", "exit", "выход"):
            return 0
        if choice == "":
            pull_new(env, url, token)
            continue
        if choice == "s":
            _resync(env, url, user, token, io)
            continue
        row = next((r for r in rows if str(r["number"]) == choice), None)
        if not choice.isdigit() or row is None:
            io.write("нет такого номера\n")
            continue
        if not row.get("available", True):
            io.write("\x1b[33mзадание сейчас недоступно\x1b[0m\n")
            continue
        _run_from_menu(env, url, user, token, int(choice), io)


def _run_from_menu(env: Home, url: str, user: str, token: str,  # noqa: PLR0913, PLR0917
                   number: int, io: Io) -> None:
    """Run a task from the menu, then offer to go straight to the next one (hand-holding flow)."""
    current: int | None = number
    while current is not None:
        cmd_pool_run(env, str(current), io)
        nxt = _next_number(pool_status(env, url, token, user), current)
        if nxt is None:
            io.write("\x1b[32mВсе доступные задания зачтены!\x1b[0m\n")
            return
        ans = (io.read(f"Перейти к следующему заданию №{nxt}? "
                       "[Enter — да, номер — другое, q — в меню]: ") or "").strip().lower()
        if ans in ("q", "quit", "exit", "выход"):
            return
        current = int(ans) if ans.isdigit() else nxt


def cmd_pool_run(env: Home, arg: str, io: Io | None = None) -> int:
    """Student run: resolve a number/ref, ensure it's pulled, run it, and submit on completion."""
    io = io or _default_io()
    url, user = _require_pool_identity(env, io)
    token = _pool_token(env, url) or ""
    client0 = RemoteRegistry(url)
    ref = _resolve_pool_ref(client0, token, arg)
    entry = next((e for e in client0.catalog(token=token) if str(e["ref"]) == ref), None)
    if entry is not None and not entry.get("available", True):
        io.write("\x1b[33mзадание сейчас недоступно\x1b[0m\n")   # visible in the list, but locked
        return 0
    store = ImageStore(env.images)
    if not store.exists(ref):
        pull_new(env, url, token)

    def _submit(completed: bool) -> None:  # noqa: FBT001  (matches the on_complete callback)
        if not completed:
            return  # only report a real completion; the server digest-gates the credit
        mark_solved(env, ref)   # record «решено» before the network, so a failed submit still
        io.write("\x1b[32m✓ решено\x1b[0m\n")   # leaves a clear local status
        digest = task_digest(task_dir(ref, store))
        try:
            result = RemoteRegistry(url).submit(ref, digest, passed=True, token=token)
        except (urllib.error.URLError, RuntimeError, ValueError) as exc:
            io.write(f"\x1b[33m⚠ не зачтено (нет связи?): {exc}\x1b[0m\n"
                     "\x1b[2m  позже нажмите s в меню для самопроверки\x1b[0m\n")
            return
        if result.get("status") == "passed":
            io.write("\x1b[32m★ зачтено\x1b[0m\n")
        else:
            io.write(f"\x1b[33mне зачтено: {result.get('reason', result.get('status'))}"
                     "\x1b[0m\n")

    return cmd_run(env, ref, io, student_id=user, on_complete=_submit)


def task_mode(env: Home, io: Io | None = None) -> int:
    """No-arg mode: list the built tasks, let the user pick one by number, and run it."""
    io = io or _default_io()
    store = ImageStore(env.images)
    tasks = [ref for ref in store.list() if _kind(store, ref) == "task"]
    if not tasks:
        io.write("заданий пока нет — автор сначала делает `hashengine build <Taskfile>`\n")
        return 0
    for i, ref in enumerate(tasks, 1):
        io.write(f"{i}. {ref}\n")
    idx = select_index(io.read("выберите № задания (пусто — выход): "), len(tasks))
    if idx is None:
        return 0
    return cmd_run(env, tasks[idx], io)


_EXIT_ABORTED = 130  # conventional shell exit code for Ctrl-C / EOF


def run_main(parser: argparse.ArgumentParser,
             dispatch: Callable[[Home, argparse.Namespace], int],
             argv: Sequence[str] | None) -> int:
    """
    Parse argv, build the env, and route via `dispatch` under a common error boundary.

    Never dumps a traceback on an ordinary user error. Shared by the `hashpass` (student)
    and `hashengine` (author) front ends; each supplies its own parser and dispatch,
    including how a missing sub-command is handled.
    """
    real_argv = list(argv) if argv is not None else sys.argv[1:]
    with contextlib.suppress(Exception):   # self-update is best-effort; never block the CLI
        check_and_update(resolve_root(os.environ, default_home=Path.home()),
                         parser.prog, real_argv)
    args = parser.parse_args(argv)
    try:
        env = build_env()
        return dispatch(env, args)
    except (KeyboardInterrupt, EOFError):
        sys.stderr.write(f"\n{parser.prog}: прервано\n")
        return _EXIT_ABORTED
    except (OSError, ValueError, RuntimeError, KeyError,
            urllib.error.URLError, subprocess.CalledProcessError) as exc:
        # bad Taskfile, missing base rootfs, push-before-login, unknown ref, bad URL, failed step.
        sys.stderr.write(f"{parser.prog}: {exc}\n")
        return 1
