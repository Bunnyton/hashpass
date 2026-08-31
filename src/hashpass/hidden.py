"""Build the hidden `/hp` host tree bound into handler/check runs (§4.1)."""
import shutil
from pathlib import Path

_HP_SUBDIRS = ("bin", "task", "work")


def stage_hidden_layer(hp_dir: Path, *, work_src: Path | None = None,
                       bundle_dir: Path | None = None) -> Path:
    """
    Build the hidden `/hp` host tree that a task binds into handler runs (§4.1).

    Layout: `<hp_dir>/{bin,task,work}` + `state.json`="{}" (rw session) + `history`="".
    `work_src` (the recipe's `hidden` dir) is copied into `work/`; `bundle_dir`
    (the derived acceptance bundle) is copied into `task/`. Pure host filesystem.

    Args:
        hp_dir: Destination host directory for the `/hp` tree (created on demand).
        work_src: Optional author `hidden` directory copied into `work/`.
        bundle_dir: Optional derived-checks bundle directory copied into `task/`.

    Returns:
        The `hp_dir` path (now populated).

    """
    hp_dir = Path(hp_dir)
    for sub in _HP_SUBDIRS:
        (hp_dir / sub).mkdir(parents=True, exist_ok=True)
    (hp_dir / "state.json").write_text("{}", encoding="utf-8")
    (hp_dir / "history").write_text("", encoding="utf-8")
    if work_src is not None:
        shutil.copytree(work_src, hp_dir / "work", dirs_exist_ok=True)
    if bundle_dir is not None:
        shutil.copytree(bundle_dir, hp_dir / "task", dirs_exist_ok=True)
    return hp_dir
