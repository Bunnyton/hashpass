"""Local task store: task artifacts (bundle + hidden /hp + meta) under the image's ver dir."""
import json
from dataclasses import dataclass
from pathlib import Path

from hashpass.imagestore.store import ImageStore, StoredImage


@dataclass(frozen=True)
class StageMeta:
    """Per-stage runtime metadata: acceptance mode + delegated actions + neutral set."""

    message: str
    neutral: tuple[str, ...]
    check: str | None            # ExecAction.value, or None
    on_enter: tuple[str, ...]    # ExecAction.value list
    on_pass: tuple[str, ...]     # ExecAction.value list
    acceptance: str              # "derived" | "handler"


@dataclass(frozen=True)
class TaskMeta:
    """Task runtime metadata: the built image ref, ordered stages, optional readme."""

    image_ref: str
    stages: tuple[StageMeta, ...]
    readme: str | None = None


@dataclass(frozen=True)
class StoredTask:
    """A stored task: its ref, the built image, and on-disk bundle/hidden/meta artifacts."""

    ref: str
    image: StoredImage
    bundle_dir: Path
    hp_src_dir: Path
    meta: TaskMeta


def task_dir(ref: str, store: ImageStore) -> Path:
    """Return the task-artifacts directory for a stored image ref (`.../ver/task`)."""
    return store.get(ref).layer.parent / "task"


def _stage_to_dict(s: StageMeta) -> dict:
    return {
        "message": s.message,
        "neutral": list(s.neutral),
        "check": s.check,
        "on_enter": list(s.on_enter),
        "on_pass": list(s.on_pass),
        "acceptance": s.acceptance,
    }


def _stage_from_dict(d: dict) -> StageMeta:
    return StageMeta(
        message=d["message"],
        neutral=tuple(d["neutral"]),
        check=d["check"],
        on_enter=tuple(d["on_enter"]),
        on_pass=tuple(d["on_pass"]),
        acceptance=d["acceptance"],
    )


def meta_to_dict(meta: TaskMeta) -> dict:
    """Serialize TaskMeta to a JSON-ready dict."""
    return {
        "image_ref": meta.image_ref,
        "stages": [_stage_to_dict(s) for s in meta.stages],
        "readme": meta.readme,
    }


def meta_from_dict(data: dict) -> TaskMeta:
    """Rebuild TaskMeta from its JSON dict."""
    return TaskMeta(
        image_ref=data["image_ref"],
        stages=tuple(_stage_from_dict(s) for s in data["stages"]),
        readme=data.get("readme"),
    )


def save_meta(meta: TaskMeta, dest: Path) -> None:
    """Write `<dest>/task-meta.json` (dest is the task-artifacts dir)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "task-meta.json").write_text(
        json.dumps(meta_to_dict(meta), indent=2), encoding="utf-8")


def load_meta(src: Path) -> TaskMeta:
    """Read `<src>/task-meta.json` back into a TaskMeta."""
    text = (Path(src) / "task-meta.json").read_text(encoding="utf-8")
    return meta_from_dict(json.loads(text))


def load_task(ref: str, store: ImageStore) -> StoredTask:
    """Load a stored task's artifacts (bundle dir, hidden `/hp` dir, and meta)."""
    tdir = task_dir(ref, store)
    return StoredTask(
        ref=ref,
        image=store.get(ref),
        bundle_dir=tdir / "bundle",
        hp_src_dir=tdir / "hp",
        meta=load_meta(tdir),
    )
