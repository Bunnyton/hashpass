"""Run a stored task: student container WITHOUT /hp; handlers/checks/hints in a bound-/hp run."""
import contextlib
import re
import shutil
import sys
import textwrap
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from hashpass.cmd import Cmd
from hashpass.grade import grade_stage
from hashpass.handler import HandlerContext, run_handler
from hashpass.hints import match_rule
from hashpass.image.base import build_base
from hashpass.imagestore.resolve import resolve_lowers
from hashpass.imagestore.store import ImageStore
from hashpass.key import local_key
from hashpass.markdown import render_markdown
from hashpass.paths import absolutize, looks_like_path, resolve_path
from hashpass.play import capture_candidate
from hashpass.progress import current_stage, mark_passed_local, new_progress
from hashpass.recipe.model import (
    Action,
    ApplyAction,
    ExecAction,
    ReadAction,
    SayAction,
    ShowFileAction,
)
from hashpass.render import Renderer
from hashpass.runner.nspawn import NspawnRunner
from hashpass.taskcode.bundle import load_bundle
from hashpass.taskcode.derive import StageChecks
from hashpass.taskcode.execute import OUTPUT_KEY
from hashpass.taskstore import StageMeta, StoredTask, TaskMeta, load_task

_ACCEPT_EXIT = 0


@dataclass
class FeedResult:
    """Outcome of feeding one student command; `hint` carries a fired hint's rendered text."""

    advanced: bool
    stage: int | None
    local_key: str | None
    hint: str | None = None


def _stdout(text: str) -> None:
    """Default render sink: write to stdout without an added newline."""
    sys.stdout.write(text)


def _is_neutral(command: str, neutral: tuple[str, ...]) -> bool:
    """
    Return True if the command's base command is a neutral ("just looking") command.

    An unparseable command (e.g. an unbalanced-quote typo, which makes `shlex` raise) is
    treated as a real attempt, never neutral — so a typo still counts toward tries and
    never crashes the session.
    """
    try:
        return Cmd(command).basecmd in neutral
    except ValueError:
        return False


def _base_cmds(command: str) -> list[str]:
    """Return the base command of every segment of a command line (split on `| && || ;`), no sudo."""
    out: list[str] = []
    for seg in re.split(r"\s*(?:\|\||&&|;|\|)\s*", command.strip()):
        if not seg.strip():
            continue
        try:
            base = Cmd(seg).basecmd
        except ValueError:
            continue
        if base:
            out.append(base)
    return out


def _blocked(sm: StageMeta, command: str) -> str | None:
    """Return the message of the first `block` rule this command trips (any segment), else None."""
    for raw in _SEG_SPLIT.split(command):
        seg = raw.strip()
        words = seg.split()
        if not words:
            continue
        base = words[1] if words[0] == "sudo" and len(words) > 1 else words[0]
        for rule in getattr(sm, "blocks", ()):
            if rule.base != base:
                continue
            hit = re.search(rule.pattern, seg) is not None
            if hit == (rule.mode == "match"):
                return rule.message
    return None


def _policy_violation(sm: StageMeta, command: str) -> str | None:
    """
    Message if `command` breaks the stage's command policy, else None (used to GATE acceptance).

    `deny`: the command may not use a forbidden base command (solve it another way). `allow`:
    the accepting command must use one of the whitelisted base commands. Applied only to a command
    that would otherwise pass, so navigation (`ls`, `cd`) never trips it.
    """
    blocked = _blocked(sm, command)
    if blocked is not None:
        return blocked
    bases = _base_cmds(command)
    if sm.deny:
        bad = next((b for b in bases if b in sm.deny), None)
        if bad is not None:
            return f"Команда «{bad}» здесь запрещена — решите задачу иначе."
    if sm.allow and not any(b in sm.allow for b in bases):
        return f"Засчитывается только через: {', '.join(sm.allow)}."
    return None


def _elapsed(start_ts: str, now_ts: str) -> float:
    """Seconds between two ISO timestamps; 0.0 if either is unparseable (idle stays neutral)."""
    try:
        return (datetime.fromisoformat(now_ts) - datetime.fromisoformat(start_ts)).total_seconds()
    except (ValueError, TypeError):
        # ValueError: unparseable ts; TypeError: mixed tz-aware/naive subtraction. Idle stays neutral.
        return 0.0


_PAGE_RESERVE = 3       # rows kept free under a page: the «далее» line and the prompt
_PAGE_MIN = 8
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


# The system's own talk (say, read, hints) carries a thin cyan bar on every line, so it never
# blends with the student's input (the plain prompt) or with the task (bold yellow bar, cli).
NARRATION_GUTTER = "\x1b[36m│\x1b[0m "
_GUTTER_COLS = 2


def _narrate(text: str, *, wrap: bool = False) -> str:
    """Prefix every line with the narration bar; `wrap` re-flows plain text to the terminal width."""
    body = text.removesuffix("\n")
    lines = body.split("\n")
    if wrap:
        width = max(20, _screen()[1] - _GUTTER_COLS)
        lines = [part for ln in lines for part in (textwrap.wrap(ln, width) or [""])]
    return "\n".join(NARRATION_GUTTER + ln for ln in lines) + "\n"


def _screen() -> tuple[int, int]:
    """
    Rows and columns of the student's terminal.

    The console (`systemd-nspawn` in the foreground) runs on the SAME terminal as this host
    process, so its size is ours; off a terminal (tests) a classic 80x24 is assumed.
    """
    size = shutil.get_terminal_size(fallback=(80, 24))
    return size.lines, size.columns


def _no_pause() -> None:
    """Default pager pause: do nothing (used off the interactive socket, e.g. in tests)."""


def _resolve_asset(path: str, hp_dir: Path, rootfs: Path, workdir: str) -> Path | None:
    """
    Resolve a `read`/`show file` source: the hidden /hp layer first, else the system FS.

    The hidden layer (`<hp_dir>/work/<path>`) wins. Otherwise the file is looked up on the
    student's system: an absolute path from the container root, a relative path under `workdir`
    (the `settings workdir`, default the student's home). Returns the file, or None if missing.
    """
    rel = path.lstrip("/")   # never let an absolute path reset the join off the intended root
    hp_file = hp_dir / "work" / rel
    if hp_file.is_file():
        return hp_file
    root = Path(rootfs)
    sys_file = root / rel if path.startswith("/") else root / workdir.lstrip("/") / rel
    return sys_file if sys_file.is_file() else None


def _read_narrative(path: str, hp_dir: Path, rootfs: Path, workdir: str) -> str:
    """Read a `read <file>` source via `_resolve_asset` (hidden layer, else the system FS)."""
    resolved = _resolve_asset(path, hp_dir, rootfs, workdir)
    if resolved is None:
        return f"(read: файл не найден: {path})"
    return resolved.read_text(encoding="utf-8", errors="replace")


def _paginate(text: str, height: int | None = None, width: int | None = None) -> list[str]:
    """
    Split narrative into pages: first on `---` marker lines, then by what fits on the screen.

    A page fills the real terminal (minus a few rows for the «далее» line and the prompt); a
    line longer than the width counts as the rows it wraps into (colour codes take no room).
    """
    rows, cols = _screen()
    cols -= _GUTTER_COLS                     # every page line carries the narration bar
    height = height if height is not None else max(_PAGE_MIN, rows - _PAGE_RESERVE)
    width = max(1, width if width is not None else cols)
    pages: list[str] = []
    for section in re.split(r"(?m)^---[ \t]*$", text):
        lines = section.strip("\n").splitlines()
        if not any(ln.strip() for ln in lines):
            continue
        page: list[str] = []
        used = 0
        for ln in lines:
            need = max(1, -(-len(_ANSI.sub("", ln)) // width))
            if page and used + need > height:
                pages.append("\n".join(page))
                page, used = [], 0
            page.append(ln)
            used += need
        if page:
            pages.append("\n".join(page))
    return pages or [text]


def _render_pages(pages: list[str], render: Renderer, pause: Callable[[], bool | None]) -> None:
    """
    Stream pages with a pause between them; a pause that answers True («q») skips ahead.

    Skipping loses nothing: the rest is printed at once, without further pauses.
    """
    skip = False
    for idx, page in enumerate(pages):
        render.render(_narrate(page + "\n"), mode="instant" if skip else "normal")
        if not skip and idx < len(pages) - 1:
            skip = bool(pause())


def perform_action(action: Action, ctx: HandlerContext, *, render: Renderer,  # noqa: PLR0913
                   runner: NspawnRunner, hp_dir: Path, workdir: str = "/",
                   pause: Callable[[], bool | None] = _no_pause) -> str:
    """
    Render one delegated action and return the text shown.

    `say` renders its literal text (dramatic pacing when flagged); `show file` and `read`
    resolve their file in the hidden `/hp` layer first, else on the student's system FS
    relative to `workdir` (see `_resolve_asset`); `exec` runs the §6 handler under `/hp` and
    renders its stdout instantly. System replies use the configured type-mode.

    Paths come from the trusted recipe author (§5 — the student is the threat, not the author).
    """
    # every action ends with a trailing newline — otherwise consecutive `say`/`exec` actions
    # concatenate visually ("ls /home/student/roomПервая команда — самая простая…") and each
    # hint smashes into the shell's next prompt on the same line.
    if isinstance(action, SayAction):
        render.render(_narrate(action.text, wrap=True), mode="dramatic" if action.dramatic else None)
        return action.text
    if isinstance(action, ShowFileAction):
        resolved = _resolve_asset(action.path, Path(hp_dir), runner.rootfs, workdir)
        if resolved is None:
            msg = f"(show file: файл не найден: {action.path})\n"
            render.render(msg, mode="instant")
            return msg
        return render.show_file(resolved)
    if isinstance(action, ReadAction):
        text = _read_narrative(action.path, Path(hp_dir), runner.rootfs, workdir)
        _render_pages(_paginate(render_markdown(text)), render, pause)
        return text
    if isinstance(action, ApplyAction):
        # The script TEXT travels, not the /hp tree: it runs in the student's live system (root),
        # so its changes are real and visible, and nothing of the hidden layer is mounted there.
        script = (Path(hp_dir) / "work" / action.path).read_text(encoding="utf-8")
        res = getattr(runner, "run_live", runner.run)(["sh", "-c", script])
        if res.stdout:
            render.render(res.stdout if res.stdout.endswith("\n") else res.stdout + "\n",
                          mode="instant")
        return res.stdout
    res = run_handler(runner, ExecAction(action.value), ctx, hp_dir=Path(hp_dir))
    out = res.stdout if res.stdout.endswith("\n") else res.stdout + "\n"
    render.render(out, mode="instant")   # program output (e.g. ASCII art) appears at once, not typed
    return res.stdout


_SEG_SPLIT = re.compile(r"\s*(?:\|\||&&|;|\|)\s*")
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SUDO_OPTS_WITH_ARG = frozenset(("-u", "-g", "-C", "-D", "-h", "-p", "-r", "-R", "-t", "-T", "-U",
                                 "--user", "--group", "--chdir", "--host", "--prompt", "--role",
                                 "--chroot", "--type", "--command-timeout", "--other-user"))


def _without_sudo(segment: str) -> str:
    """
    Normalize a command segment so the pattern anchors on the real command.

    Drops env assignments (`LANG=C cmd`), a leading `sudo` with its own options (`-u bob`
    consumes its argument) and reduces a path in the first word to its basename
    (`/usr/games/sl` -> `sl`, `./cmatrix` -> `cmatrix`).
    """
    tokens = segment.split()
    while tokens and _ENV_ASSIGN.match(tokens[0]):   # `LANG=C cmd`
        tokens = tokens[1:]
    if tokens and tokens[0] == "sudo":
        tokens = tokens[1:]
        while tokens and tokens[0].startswith("-"):
            opt, tokens = tokens[0], tokens[1:]
            if opt in _SUDO_OPTS_WITH_ARG:            # `sudo -u bob cmd`: `bob` is not the command
                tokens = tokens[1:]
        while tokens and _ENV_ASSIGN.match(tokens[0]):   # `sudo LANG=C cmd`
            tokens = tokens[1:]
    if tokens and "/" in tokens[0]:
        tokens[0] = tokens[0].rsplit("/", 1)[-1] or tokens[0]
    return " ".join(tokens)


def _is_option(word: str) -> bool:
    return word.startswith("-") and word != "-"


def _word_matches(want: str, got: str) -> bool:
    """Match one pattern word exactly; a word ending in `/` or `.` (`./`) matches by prefix."""
    return want == got or (not (want[-1].isalnum() or want[-1] in "_-") and got.startswith(want))


def _same_file(want: str, got: str, cwd: str, exists: Callable[[str], bool]) -> bool:
    """Whether two words, at least one spelled as a path, resolve to the same existing file."""
    if not (looks_like_path(want) or looks_like_path(got)):
        return False
    path = resolve_path(want.rstrip("/") or "/", cwd)
    return path == resolve_path(got.rstrip("/") or "/", cwd) and exists(path)


def _cmd_matches(pattern: str, command: str, *, cwd: str | None = None,
                 exists: Callable[[str], bool] | None = None) -> bool:
    """
    Whether an `accept cmd` pattern names the command the student ran.

    Per pipeline segment (after an optional `sudo`; a path in the first word counts by its
    basename): the pattern's POSITIONAL words must be exactly the command's leading positional
    words, in order (`apt update` is not `apt search update`, `man man` is not `man ls man`),
    while the pattern's OPTION words (`-…`) may sit anywhere among the command's options -- so
    an alias the student's shell expands (`ls --help` arrives as `ls --color=auto --help` from a
    fresh user's ~/.bashrc) still matches. `sleep` never counts as `sl`, `dpkg -s cmatrix` never
    as `cmatrix`. A pattern word ending in `/` or `.` (`apt install ./`) matches by prefix. The
    live console ships the LAST simple command of a pipeline/`&&` chain; the segment split
    matters for the test/`feed()` path, which sees the whole line.

    A word that names an existing file names it in any spelling: with the student's `cwd`,
    `cat os-release` run in /etc is `cat /etc/os-release` (root-tour, 2026-10-14) -- the same
    rule as for paths in the output (`paths.absolutize`).
    """
    def same(w: str, g: str) -> bool:
        return _word_matches(w, g) or (cwd is not None and exists is not None
                                       and _same_file(w, g, cwd, exists))

    want = _without_sudo(pattern).split()   # the pattern may spell `sudo` too
    if not want:
        return False
    want_pos = [w for w in want if not _is_option(w)]
    want_opt = [w for w in want if _is_option(w)]
    for raw in _SEG_SPLIT.split(command.strip()):
        got = _without_sudo(raw).split()
        got_pos = [w for w in got if not _is_option(w)]
        got_opt = [w for w in got if _is_option(w)]
        if len(got_pos) < len(want_pos) or not all(
                same(w, g) for w, g in zip(want_pos, got_pos, strict=False)):
            continue
        if all(any(_word_matches(w, g) for g in got_opt) for w in want_opt):
            return True
    return False


def _accepted_by_cmd(sm: StageMeta, command: str, rc: int | None, *, cwd: str | None = None,
                     exists: Callable[[str], bool] | None = None) -> bool:
    """
    Whether `command` passes the stage by an `accept cmd` match (see `_cmd_matches`).

    With `accept cmd "…" ok` the command must also have exited 0; an unknown status (an older
    console that does not report it) is not held against the student.
    """
    if not sm.accept_cmds or not any(_cmd_matches(sub, command, cwd=cwd, exists=exists)
                                     for sub in sm.accept_cmds):
        return False
    return not (sm.accept_ok and rc is not None and rc != 0)


def _texts_hold(sm: StageMeta, out: str, read: Callable[[str], str | None]) -> bool:
    """Every `accept output|file "<ERE>"` holds: the pattern is found (None = the output is empty)."""
    for target, pattern in sm.accept_texts:
        text = out if target == "output" else read(target)
        if text is None:
            return False
        if pattern is None:
            if text.strip():
                return False
        elif re.search(pattern, text, re.MULTILINE) is None:
            return False
    return True


def _command_gates(sm: StageMeta, command: str, rc: int | None, out: str, *,  # noqa: PLR0913
                   read: Callable[[str], str | None], cwd: str | None = None,
                   exists: Callable[[str], bool] | None = None) -> bool | None:
    """
    Run the Taskfile-written checks on the command itself: `accept cmd` and `accept output|file`.

    None when the stage has none; otherwise whether ALL of them hold. They combine with an
    `observe` or a `check exec` in the same stage (sudo-basics: `accept cmd "rm"` + the file is
    still there) -- every check present must pass.
    """
    if not sm.accept_cmds and not sm.accept_texts:
        return None
    if sm.accept_cmds and not _accepted_by_cmd(sm, command, rc, cwd=cwd, exists=exists):
        return False
    return _texts_hold(sm, out, read)


def normalize_output_checks(checks: StageChecks, out: str, *, cwd: str, workdir: str,
                            exists: Callable[[str], bool]) -> tuple[StageChecks, str]:
    """
    Make file paths absolute on BOTH sides of an `observe output` comparison.

    The reference was derived from `workdir`; the student's command ran in `cwd` -- `find .` from
    ~/search and `find search` from ~ print the same files differently. A stage without an output
    check is returned as is.
    """
    want = checks.canonical.get(OUTPUT_KEY)
    if want is None or want.text is None:
        return checks, out
    canonical = dict(checks.canonical)
    canonical[OUTPUT_KEY] = replace(want, text=absolutize(want.text, cwd=workdir, exists=exists))
    return replace(checks, canonical=canonical), absolutize(out, cwd=cwd, exists=exists)


def theory_actions(meta: TaskMeta, *, stage: int | None,
                   fired: list[set[int]]) -> list[ReadAction]:
    """
    Collect the theory a student has been given so far, in order -- what `readme` replays.

    The brief (`read` before the first step), each reached step's `on enter read` and every
    `hint … read` that already fired; never a later step's dose. `stage` None = all done.
    """
    last = len(meta.stages) - 1 if stage is None else stage
    out = [a for a in meta.intro if isinstance(a, ReadAction)]
    for i, sm in enumerate(meta.stages[:last + 1]):
        out += [a for a in sm.on_enter if isinstance(a, ReadAction)]
        out += [h.action for j, h in enumerate(sm.hints)
                if j in fired[i] and isinstance(h.action, ReadAction)]
    return out


class TaskSession:
    """One student's live task run: a /hp-free student container + per-session hidden /hp."""

    def __init__(self, stored: StoredTask, student: NspawnRunner, hp_dir: Path, *,  # noqa: PLR0913
                 student_id: str, nonce: str,
                 sink: Callable[[str], None] = _stdout,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        """Bind a stored task to a prepared (student) runner, a writable /hp copy, and a Renderer."""
        self.stored = stored
        self.student = student
        self.hp_dir = Path(hp_dir)
        self.meta = stored.meta
        self.checks = load_bundle(stored.bundle_dir).checks
        self.task_id = self.checks.task_id
        self.student_id = student_id
        self.nonce = nonce
        self.progress = new_progress(self.task_id, len(stored.meta.stages))
        self.tries = [0] * len(stored.meta.stages)
        self._fired: list[set[int]] = [set() for _ in stored.meta.stages]  # hint rules fired, per stage
        self.render = Renderer(self.meta.settings, sink=sink, sleep=sleep)
        self._greeted = False
        self._said_bye = False
        self._last_progress_ts: str | None = None
        self._cwd: str | None = None    # where the student's last command ran (console runtime >= 43)
        self.pause: Callable[[], bool | None] = _no_pause   # pager pause (True = skip the rest)

    def _record(self, command: str) -> None:
        """
        Append the student's command to `/hp/history` (HP_HISTORY): one command per line.

        Lets a `check exec` grader see every command of the session, not only the last one.
        """
        line = "; ".join(part.strip() for part in command.splitlines() if part.strip())
        with contextlib.suppress(OSError), (self.hp_dir / "history").open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _exists(self, path: str) -> bool:
        """Whether `path` exists in the student's system (for reading paths in an output)."""
        try:
            return (Path(self.student.rootfs) / path.lstrip("/")).exists()
        except (OSError, AttributeError, TypeError):
            return False

    def _read_file(self, path: str) -> str | None:
        """Read a text file of the student's system (`accept file`); None if it is not there."""
        try:
            return (Path(self.student.rootfs) / path.lstrip("/")).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, AttributeError, TypeError):
            return None

    def _ctx(self, command: str, tries: int, stage: int, last_out: str = "") -> HandlerContext:
        """Build the HP_* handler context for one delegated action (with the output's paths made absolute)."""
        cwd = self._cwd or self.meta.settings.workdir
        absolute = absolutize(last_out, cwd=cwd, exists=self._exists) if last_out else ""
        return HandlerContext(student_cmd=command, tries=tries, last_out=last_out, stage=stage,
                              cwd=cwd, last_out_abs=absolute)

    def _perform_all(self, actions: tuple[Action, ...], ctx: HandlerContext) -> list[str]:
        """Render a list of delegated actions; collect the text each produced."""
        return [perform_action(a, ctx, render=self.render, runner=self.student,
                               hp_dir=self.hp_dir, workdir=self.meta.settings.workdir,
                               pause=self.pause) for a in actions]

    def enter(self) -> list[str]:
        """Fire session `voice hello` (first call) then the current stage's `on_enter`; return their text."""
        # kept as-is for stages > 1 (announce + enter pair happens together at stage advance);
        # stage 1's initial intro flow uses `greet_once()` / `enter_stage()` separately so the
        # on_enter fires AFTER the top-level intro + brief + announce (not before them).
        stage = current_stage(self.progress)
        outs: list[str] = self.greet_once()
        if stage is None:
            return outs
        sm = self.meta.stages[stage]
        outs.extend(self._perform_all(sm.on_enter, self._ctx("", self.tries[stage], stage)))
        return outs

    def greet_once(self) -> list[str]:
        """Fire `voice hello` — only the first time it's called; a no-op afterwards."""
        if self._greeted:
            return []
        self._greeted = True
        stage = current_stage(self.progress) or 0
        return self._perform_all(self.meta.voice.hello, self._ctx("", 0, stage))

    def enter_stage(self) -> list[str]:
        """Fire the current stage's `on_enter` only (no `voice.hello`)."""
        stage = current_stage(self.progress)
        if stage is None:
            return []
        sm = self.meta.stages[stage]
        return self._perform_all(sm.on_enter, self._ctx("", self.tries[stage], stage))

    def fire_intro(self) -> list[str]:
        """Render the top-level `intro` actions (author opener, before the first stage)."""
        return self._perform_all(self.meta.intro, self._ctx("", 0, current_stage(self.progress) or 0))

    def fire_outro(self) -> list[str]:
        """Render the top-level `outro` actions (author closer, after the last stage passes)."""
        return self._perform_all(self.meta.outro, self._ctx("", 0, 0))

    def replay_theory(self) -> None:
        """`readme` in the console: show the theory given so far once more (paged, no typing)."""
        acts = theory_actions(self.meta, stage=current_stage(self.progress), fired=self._fired)
        if not acts:
            self.render.render(_narrate("Теории у этого задания нет — всё сказано в цели."),
                               mode="instant")
            return
        self._perform_all(acts, self._ctx("", 0, current_stage(self.progress) or 0))

    def read_text(self, text: str) -> None:
        """Render a Markdown STRING as paged, streamed narrative (the readme briefing)."""
        _render_pages(_paginate(render_markdown(text)), self.render, self.pause)

    def _accept(self, stage: int, sm: StageMeta, command: str,  # noqa: PLR0913
                out: str, ts: str, *, rc: int | None = None) -> tuple[bool, str | None]:
        """Decide acceptance: `accept cmd` match, else handler check-run, else derived host-side."""
        gates = _command_gates(sm, command, rc, out, read=self._read_file,
                               cwd=self._cwd or self.meta.settings.workdir, exists=self._exists)
        if gates is False:
            return False, None
        if sm.acceptance == "command":   # accepted ONLY by the command's own checks (no FS grading)
            return (True, local_key(self.task_id, stage, self.nonce)) if gates else (False, None)
        if sm.acceptance == "handler":
            ctx = self._ctx(command, self.tries[stage], stage, out)
            res = run_handler(self.student, ExecAction(sm.check), ctx, hp_dir=self.hp_dir)
            if res.exit_code == _ACCEPT_EXIT:
                return True, local_key(self.task_id, stage, self.nonce)
            return False, None
        # Derived: FS observation and/or `observe output`. `out` is the student's CLEAN stdout
        # (extracted from the console's OSC-133 marks), so grade_stage compares it to the reference
        # by the derived `settings similarity` threshold -- strict at 100, fuzzy below.
        checks, out = normalize_output_checks(
            self.checks.stages[stage], out, cwd=self._cwd or self.meta.settings.workdir,
            workdir=self.meta.settings.workdir, exists=self._exists)
        cand = capture_candidate(self.student.rootfs, checks, out)
        grade = grade_stage(checks, cand, task_id=self.task_id,
                            stage=stage, student_id=self.student_id, nonce=self.nonce, ts=ts)
        return grade.accepted, grade.local_key

    def _apply_policy(self, sm: StageMeta, command: str, accepted: bool,  # noqa: FBT001
                      key: str | None) -> tuple[bool, str | None, str | None]:
        """
        Gate a would-be pass by the stage's `deny`/`allow` command policy.

        Returns (accepted, key, hint). Only a passing command is checked, so navigation is never
        blocked; a violation cancels the pass and surfaces the policy message as the hint.
        """
        if not accepted:
            return accepted, key, None
        violation = _policy_violation(sm, command)
        if violation is None:
            return accepted, key, None
        self.render.render(violation + "\n", mode="normal")
        return False, None, violation

    def _on_pass(self, stage: int, ctx: HandlerContext, ts: str) -> None:
        """Fire `on_pass`, advance progress, and speak `voice bye` once all stages pass."""
        self._last_progress_ts = ts
        mark_passed_local(self.progress, stage)
        self._perform_all(self.meta.stages[stage].on_pass, ctx)
        if current_stage(self.progress) is None and not self._said_bye:
            self._said_bye = True
            self._perform_all(self.meta.voice.bye, ctx)

    def feed(self, command: str, *, ts: str) -> FeedResult:
        """Run one student command (no /hp), tally tries, react, check acceptance, maybe hint."""
        self._record(command)
        stage = current_stage(self.progress)
        if stage is None:
            return FeedResult(advanced=False, stage=None, local_key=None)
        if self._last_progress_ts is None:
            self._last_progress_ts = ts
        sm = self.meta.stages[stage]
        out = self.student.run(["sh", "-c", command]).stdout
        self.render.render(out, mode="instant")          # student output is never typed (§7.2)
        if not _is_neutral(command, sm.neutral):
            self.tries[stage] += 1
        ctx = self._ctx(command, self.tries[stage], stage, out)
        self._perform_all(self.meta.react, ctx)          # per-command catch-all handlers
        accepted, key = self._accept(stage, sm, command, out, ts)
        accepted, key, hint = self._apply_policy(sm, command, accepted, key)
        if accepted:
            self._on_pass(stage, ctx, ts)
        elif hint is None:
            action = match_rule(sm.hints, tries=self.tries[stage],
                                idle=_elapsed(self._last_progress_ts, ts),
                                command=command, output=out, fired=self._fired[stage])
            if action is not None:
                hint = perform_action(action, ctx, render=self.render, runner=self.student,
                                      hp_dir=self.hp_dir, workdir=self.meta.settings.workdir)
        return FeedResult(advanced=accepted, stage=stage, local_key=key, hint=hint)

    def observe(self, command: str, *, ts: str, output: str = "",
                rc: int | None = None, cwd: str | None = None) -> FeedResult:
        """
        React/grade/hint on a command the student ALREADY ran in the interactive console.

        Same as feed() but does NOT re-run the command (the console executed it). `output` is the
        command's captured stdout, streamed from the live console over the grade socket (empty when
        unavailable), so `output`-conditioned hints and output-based acceptance fire live too.
        `rc` is the command's exit status as the console reported it (None on an older runtime).
        `cwd` is the directory it ran in: paths in its output are read against it.
        """
        self._cwd = cwd
        self._record(command)
        stage = current_stage(self.progress)
        if stage is None:
            return FeedResult(advanced=False, stage=None, local_key=None)
        if self._last_progress_ts is None:
            self._last_progress_ts = ts
        sm = self.meta.stages[stage]
        out = output                                      # the console's captured stdout (may be "")
        if not _is_neutral(command, sm.neutral):
            self.tries[stage] += 1
        ctx = self._ctx(command, self.tries[stage], stage, out)
        self._perform_all(self.meta.react, ctx)          # per-command catch-all handlers
        accepted, key = self._accept(stage, sm, command, out, ts, rc=rc)
        accepted, key, hint = self._apply_policy(sm, command, accepted, key)
        if accepted:
            self._on_pass(stage, ctx, ts)
        elif hint is None:
            action = match_rule(sm.hints, tries=self.tries[stage],
                                idle=_elapsed(self._last_progress_ts, ts),
                                command=command, output=out, fired=self._fired[stage])
            if action is not None:
                hint = perform_action(action, ctx, render=self.render, runner=self.student,
                                      hp_dir=self.hp_dir, workdir=self.meta.settings.workdir)
        return FeedResult(advanced=accepted, stage=stage, local_key=key, hint=hint)

    def check_current(self, *, ts: str) -> FeedResult:
        """
        Passively grade the current stage against the student's live FS (no command).

        For background grading while the student works in a real shell: captures the
        current stage's acceptance from the live student rootfs and, on a pass, fires
        `on_pass` + advances (speaking `voice bye` once every stage is done).
        """
        stage = current_stage(self.progress)
        if stage is None:
            return FeedResult(advanced=False, stage=None, local_key=None)
        sm = self.meta.stages[stage]
        if sm.deny or sm.allow:
            # a command policy can only be judged on a real command; passive FS grading has none,
            # so it must not auto-pass a policy stage (that would bypass `deny`/`allow`).
            return FeedResult(advanced=False, stage=stage, local_key=None)
        accepted, key = self._accept(stage, sm, "", "", ts)
        if accepted:
            self._on_pass(stage, self._ctx("", self.tries[stage], stage), ts)
        return FeedResult(advanced=accepted, stage=stage, local_key=key)

    def teardown(self) -> None:
        """Tear down the student container (unmount overlay). The /hp copy is scratch."""
        self.student.teardown()


def run_task(ref: str, store: ImageStore, workdir: Path, *,  # noqa: PLR0913
             base_tar: Path | None = None, base: Path | None = None,
             student_id: str, nonce: str,
             sink: Callable[[str], None] = _stdout,
             sleep: Callable[[float], None] = time.sleep) -> TaskSession:
    """
    Open a live task session: a student container on the image chain, no `/hp` in it.

    Prepares the student NspawnRunner over the task image's overlay closure (so `/hp`
    is never a lower and never baked), makes a writable per-session copy of the stored
    hidden `/hp`, and returns a driveable TaskSession whose Renderer uses `sink`/`sleep`.

    Args:
        ref: Task/image reference (`name` or `name:version`).
        store: Image store holding the task and its image chain.
        workdir: Scratch dir for the base, the student runner tree, and the /hp copy.
        base_tar: Rootfs tarball for the bottom base layer (fallback when `base` is None).
        base: Prebuilt base rootfs layer -- the base image (`bunnyton/debian:trixie`,
            see `cli.base_ref`); when given it is used directly and `base_tar` is ignored
            (built once in the store, reused).
        student_id: Student identity (folded into evidence for derived stages).
        nonce: Per-session nonce for local keys.
        sink: Where rendered text is emitted (default stdout write).
        sleep: Pacing hook for the typewriter (default time.sleep; inject a no-op in tests).

    Returns:
        A TaskSession (call `.enter()`, `.feed(cmd, ts=...)`, `.teardown()`).

    """
    workdir = Path(workdir)
    stored = load_task(ref, store)
    lowers = resolve_lowers((ref,), store)
    base = base or build_base(workdir / "base", from_tar=base_tar)
    student = NspawnRunner(workdir / "student", base_dir=base)
    student.prepare(lowers)
    try:
        hp_dir = workdir / "hp"
        shutil.copytree(stored.hp_src_dir, hp_dir, dirs_exist_ok=True)
        return TaskSession(stored, student, hp_dir, student_id=student_id, nonce=nonce,
                           sink=sink, sleep=sleep)
    except Exception:
        # prepare() already mounted the overlay; on any failure before the caller holds a
        # TaskSession (its only teardown handle), unmount it here so we don't leak a mount.
        student.teardown()
        raise
