"""Run a stored task: student container WITHOUT /hp; handlers/checks in a bound-/hp run."""
import shutil
from dataclasses import dataclass
from pathlib import Path

from hashpass.cmd import Cmd
from hashpass.grade import grade_stage
from hashpass.handler import HandlerContext, run_handler
from hashpass.image.base import build_base
from hashpass.imagestore.resolve import resolve_lowers
from hashpass.imagestore.store import ImageStore
from hashpass.key import local_key
from hashpass.play import capture_candidate
from hashpass.progress import current_stage, mark_passed_local, new_progress
from hashpass.recipe.model import ExecAction
from hashpass.runner.nspawn import NspawnRunner
from hashpass.taskcode.bundle import load_bundle
from hashpass.taskstore import StageMeta, StoredTask, load_task

_ACCEPT_EXIT = 0


@dataclass
class FeedResult:
    """Outcome of feeding one student command (hints deferred to Phase 3, always None here)."""

    advanced: bool
    stage: int | None
    local_key: str | None
    hint: str | None = None


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


class TaskSession:
    """One student's live task run: a /hp-free student container + per-session hidden /hp."""

    def __init__(self, stored: StoredTask, student: NspawnRunner, hp_dir: Path, *,
                 student_id: str, nonce: str) -> None:
        """Bind a stored task to a prepared (student) runner and a writable /hp copy."""
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

    def _fire(self, actions: tuple[str, ...], ctx: HandlerContext) -> list[str]:
        """Run a list of delegated actions (on_enter/on_pass) under /hp; collect any stdout."""
        outs: list[str] = []
        for value in actions:
            res = run_handler(self.student, ExecAction(value), ctx, hp_dir=self.hp_dir)
            if res.stdout:
                outs.append(res.stdout)
        return outs

    def enter(self) -> list[str]:
        """Fire the current stage's `on_enter` handlers; return their rendered stdout."""
        stage = current_stage(self.progress)
        if stage is None:
            return []
        sm = self.meta.stages[stage]
        ctx = HandlerContext(student_cmd="", tries=self.tries[stage], last_out="", stage=stage)
        return self._fire(sm.on_enter, ctx)

    def _accept(self, stage: int, sm: StageMeta, command: str,
                out: str, ts: str) -> tuple[bool, str | None]:
        """Decide acceptance: handler stages via a /hp check-run; derived stages host-side."""
        if sm.acceptance == "handler":
            ctx = HandlerContext(student_cmd=command, tries=self.tries[stage],
                                 last_out=out, stage=stage)
            res = run_handler(self.student, ExecAction(sm.check), ctx, hp_dir=self.hp_dir)
            if res.exit_code == _ACCEPT_EXIT:
                return True, local_key(self.task_id, stage, self.nonce)
            return False, None
        cand = capture_candidate(self.student.rootfs, self.checks.stages[stage], out)
        grade = grade_stage(self.checks.stages[stage], cand, task_id=self.task_id,
                            stage=stage, student_id=self.student_id, nonce=self.nonce, ts=ts)
        return grade.accepted, grade.local_key

    def feed(self, command: str, *, ts: str) -> FeedResult:
        """Run one student command (no /hp), tally neutral-aware tries, check acceptance."""
        stage = current_stage(self.progress)
        if stage is None:
            return FeedResult(advanced=False, stage=None, local_key=None)
        sm = self.meta.stages[stage]
        out = self.student.run(["sh", "-c", command]).stdout
        if not _is_neutral(command, sm.neutral):
            self.tries[stage] += 1
        accepted, key = self._accept(stage, sm, command, out, ts)
        if accepted:
            mark_passed_local(self.progress, stage)
            ctx = HandlerContext(student_cmd=command, tries=self.tries[stage],
                                 last_out=out, stage=stage)
            self._fire(sm.on_pass, ctx)
        return FeedResult(advanced=accepted, stage=stage, local_key=key)

    def teardown(self) -> None:
        """Tear down the student container (unmount overlay). The /hp copy is scratch."""
        self.student.teardown()


def run_task(ref: str, store: ImageStore, workdir: Path, *,  # noqa: PLR0913
             base_tar: Path, student_id: str, nonce: str) -> TaskSession:
    """
    Open a live task session: a student container on the image chain, no `/hp` in it.

    Prepares the student NspawnRunner over the task image's overlay closure (so `/hp`
    is never a lower and never baked), makes a writable per-session copy of the stored
    hidden `/hp`, and returns a driveable TaskSession.

    Args:
        ref: Task/image reference (`name` or `name:version`).
        store: Image store holding the task and its image chain.
        workdir: Scratch dir for the base, the student runner tree, and the /hp copy.
        base_tar: Rootfs tarball for the bottom base layer.
        student_id: Student identity (folded into evidence for derived stages).
        nonce: Per-session nonce for local keys.

    Returns:
        A TaskSession (call `.enter()`, `.feed(cmd, ts=...)`, `.teardown()`).

    """
    workdir = Path(workdir)
    stored = load_task(ref, store)
    lowers = resolve_lowers((ref,), store)
    base = build_base(workdir / "base", from_tar=base_tar)
    student = NspawnRunner(workdir / "student", base_dir=base)
    student.prepare(lowers)
    try:
        hp_dir = workdir / "hp"
        shutil.copytree(stored.hp_src_dir, hp_dir, dirs_exist_ok=True)
        return TaskSession(stored, student, hp_dir, student_id=student_id, nonce=nonce)
    except Exception:
        # prepare() already mounted the overlay; on any failure before the caller holds a
        # TaskSession (its only teardown handle), unmount it here so we don't leak a mount.
        student.teardown()
        raise
