"""Run a stored task: student container WITHOUT /hp; handlers/checks/hints in a bound-/hp run."""
import re
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
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
from hashpass.play import capture_candidate
from hashpass.progress import current_stage, mark_passed_local, new_progress
from hashpass.recipe.model import Action, ExecAction, ReadAction, SayAction, ShowFileAction
from hashpass.render import Renderer
from hashpass.runner.nspawn import NspawnRunner
from hashpass.taskcode.bundle import load_bundle
from hashpass.taskstore import StageMeta, StoredTask, load_task

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


def _policy_violation(sm: StageMeta, command: str) -> str | None:
    """
    Message if `command` breaks the stage's command policy, else None (used to GATE acceptance).

    `deny`: the command may not use a forbidden base command (solve it another way). `allow`:
    the accepting command must use one of the whitelisted base commands. Applied only to a command
    that would otherwise pass, so navigation (`ls`, `cd`) never trips it.
    """
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


_READ_PAGE_LINES = 18   # auto page height for `read` when no `---` marker splits it sooner


def _no_pause() -> None:
    """Default pager pause: do nothing (used off the interactive socket, e.g. in tests)."""


def _read_narrative(path: str, hp_dir: Path, rootfs: Path) -> str:
    """Resolve a `read <file>` source: the hidden /hp layer first, else the image filesystem."""
    hp_file = hp_dir / "work" / path
    if hp_file.is_file():
        return hp_file.read_text(encoding="utf-8", errors="replace")
    try:
        return (Path(rootfs) / path.lstrip("/")).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"(read: файл не найден: {path})"


def _paginate(text: str, height: int = _READ_PAGE_LINES) -> list[str]:
    """Split narrative into pages: first on `---` marker lines, then by screen height."""
    pages: list[str] = []
    for section in re.split(r"(?m)^---[ \t]*$", text):
        lines = section.strip("\n").splitlines()
        if not any(ln.strip() for ln in lines):
            continue
        pages.extend("\n".join(lines[i:i + height]) for i in range(0, len(lines), height))
    return pages or [text]


def perform_action(action: Action, ctx: HandlerContext, *, render: Renderer,  # noqa: PLR0913
                   runner: NspawnRunner, hp_dir: Path,
                   pause: Callable[[], None] = _no_pause) -> str:
    """
    Render one delegated action and return the text shown.

    `say` renders its literal text (dramatic pacing when flagged); `show file` reads
    `<hp_dir>/work/<path>` and renders it (paged when large); `exec` runs the §6 handler
    under `/hp` and renders its stdout. System replies use the configured type-mode.

    The `show file` path comes from the trusted recipe author (§5 — the student is the
    threat, not the author); it is not confined to `work/`, so an absolute or `..` path
    reads where it points. Authors use relative paths under the hidden work dir.
    """
    if isinstance(action, SayAction):
        render.render(action.text, mode="dramatic" if action.dramatic else None)
        return action.text
    if isinstance(action, ShowFileAction):
        return render.show_file(Path(hp_dir) / "work" / action.path)
    if isinstance(action, ReadAction):
        text = _read_narrative(action.path, Path(hp_dir), runner.rootfs)
        pages = _paginate(render_markdown(text))
        for idx, page in enumerate(pages):
            render.render(page + "\n", mode="normal")   # even, streamed reveal
            if idx < len(pages) - 1:
                pause()                                   # wait for Enter between pages
        return text
    res = run_handler(runner, ExecAction(action.value), ctx, hp_dir=Path(hp_dir))
    render.render(res.stdout, mode="instant")   # program output (e.g. ASCII art) appears at once, not typed
    return res.stdout


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
        self.render = Renderer(self.meta.settings, sink=sink, sleep=sleep)
        self._greeted = False
        self._said_bye = False
        self._last_progress_ts: str | None = None
        self.pause: Callable[[], None] = _no_pause   # pager pause hook (set by the console driver)

    @staticmethod
    def _ctx(command: str, tries: int, stage: int, last_out: str = "") -> HandlerContext:
        """Build the HP_* handler context for one delegated action."""
        return HandlerContext(student_cmd=command, tries=tries, last_out=last_out, stage=stage)

    def _perform_all(self, actions: tuple[Action, ...], ctx: HandlerContext) -> list[str]:
        """Render a list of delegated actions; collect the text each produced."""
        return [perform_action(a, ctx, render=self.render, runner=self.student,
                               hp_dir=self.hp_dir, pause=self.pause) for a in actions]

    def enter(self) -> list[str]:
        """Fire session `voice hello` (first call) then the current stage's `on_enter`; return their text."""
        stage = current_stage(self.progress)
        outs: list[str] = []
        if not self._greeted:
            self._greeted = True
            outs.extend(self._perform_all(self.meta.voice.hello, self._ctx("", 0, stage or 0)))
        if stage is None:
            return outs
        sm = self.meta.stages[stage]
        outs.extend(self._perform_all(sm.on_enter, self._ctx("", self.tries[stage], stage)))
        return outs

    def fire_intro(self) -> list[str]:
        """Render the top-level `intro` actions (author opener, before the first stage)."""
        return self._perform_all(self.meta.intro, self._ctx("", 0, current_stage(self.progress) or 0))

    def fire_outro(self) -> list[str]:
        """Render the top-level `outro` actions (author closer, after the last stage passes)."""
        return self._perform_all(self.meta.outro, self._ctx("", 0, 0))

    def read_text(self, text: str) -> None:
        """Render a Markdown STRING as paged, streamed narrative (the readme briefing)."""
        pages = _paginate(render_markdown(text))
        for idx, page in enumerate(pages):
            self.render.render(page + "\n", mode="normal")
            if idx < len(pages) - 1:
                self.pause()

    def _accept(self, stage: int, sm: StageMeta, command: str,
                out: str, ts: str) -> tuple[bool, str | None]:
        """Decide acceptance: `accept cmd` match, else handler check-run, else derived host-side."""
        if sm.accept_cmds and any(sub in command for sub in sm.accept_cmds):
            return True, local_key(self.task_id, stage, self.nonce)  # a concrete solution command
        if sm.acceptance == "command":
            return False, None       # accepted ONLY by an `accept cmd` match (no FS grading)
        if sm.acceptance == "handler":
            ctx = self._ctx(command, self.tries[stage], stage, out)
            res = run_handler(self.student, ExecAction(sm.check), ctx, hp_dir=self.hp_dir)
            if res.exit_code == _ACCEPT_EXIT:
                return True, local_key(self.task_id, stage, self.nonce)
            return False, None
        # Derived: FS observation and/or `observe output`. `out` is the student's CLEAN stdout
        # (extracted from the console's OSC-133 marks), so grade_stage compares it to the reference
        # by the derived `settings similarity` threshold -- strict at 100, fuzzy below.
        cand = capture_candidate(self.student.rootfs, self.checks.stages[stage], out)
        grade = grade_stage(self.checks.stages[stage], cand, task_id=self.task_id,
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
                                command=command, output=out)
            if action is not None:
                hint = perform_action(action, ctx, render=self.render,
                                      runner=self.student, hp_dir=self.hp_dir)
        return FeedResult(advanced=accepted, stage=stage, local_key=key, hint=hint)

    def observe(self, command: str, *, ts: str, output: str = "") -> FeedResult:
        """
        React/grade/hint on a command the student ALREADY ran in the interactive console.

        Same as feed() but does NOT re-run the command (the console executed it). `output` is the
        command's captured stdout, streamed from the live console over the grade socket (empty when
        unavailable), so `output`-conditioned hints and output-based acceptance fire live too.
        """
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
        accepted, key = self._accept(stage, sm, command, out, ts)
        accepted, key, hint = self._apply_policy(sm, command, accepted, key)
        if accepted:
            self._on_pass(stage, ctx, ts)
        elif hint is None:
            action = match_rule(sm.hints, tries=self.tries[stage],
                                idle=_elapsed(self._last_progress_ts, ts),
                                command=command, output=out)
            if action is not None:
                hint = perform_action(action, ctx, render=self.render,
                                      runner=self.student, hp_dir=self.hp_dir)
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
        base: Prebuilt base rootfs layer (the `debian:trixie` image); when given it is
            used directly and `base_tar` is ignored (built once in the store, reused).
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
