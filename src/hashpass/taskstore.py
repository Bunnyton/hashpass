"""Local task store: task artifacts (bundle + hidden /hp + meta) under the image's ver dir."""
import json
from dataclasses import dataclass, field
from pathlib import Path

from hashpass.imagestore.store import ImageStore, StoredImage
from hashpass.recipe.model import (
    Action,
    CmdCond,
    Condition,
    ExecAction,
    HintRule,
    IdleCond,
    OutputCond,
    SayAction,
    Settings,
    ShowFileAction,
    TriesCond,
    Voice,
)


@dataclass(frozen=True)
class StageMeta:
    """Per-stage runtime metadata: acceptance mode + delegated actions + hints + neutral set."""

    message: str
    neutral: tuple[str, ...]
    check: str | None                 # ExecAction.value, or None
    on_enter: tuple[Action, ...]      # exec/say/show actions
    on_pass: tuple[Action, ...]
    acceptance: str                   # "derived" | "handler"
    hints: tuple[HintRule, ...] = ()


@dataclass(frozen=True)
class TaskMeta:
    """Task runtime metadata: the built image ref, ordered stages, readme, voice/settings/react."""

    image_ref: str
    stages: tuple[StageMeta, ...]
    readme: str | None = None
    voice: Voice = field(default_factory=Voice)
    settings: Settings = field(default_factory=Settings)
    react: tuple[Action, ...] = ()


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


def _action_to_dict(action: Action) -> dict:
    if isinstance(action, ExecAction):
        return {"kind": "exec", "value": action.value}
    if isinstance(action, SayAction):
        return {"kind": "say", "text": action.text, "dramatic": action.dramatic}
    if isinstance(action, ShowFileAction):
        return {"kind": "show", "path": action.path}
    msg = f"unknown action: {action!r}"
    raise TypeError(msg)


def _action_from_dict(data: dict) -> Action:
    kind = data["kind"]
    if kind == "exec":
        return ExecAction(data["value"])
    if kind == "say":
        return SayAction(data["text"], data.get("dramatic", False))
    if kind == "show":
        return ShowFileAction(data["path"])
    msg = f"unknown action kind: {kind!r}"
    raise ValueError(msg)


def _cond_to_dict(cond: Condition) -> dict:
    if isinstance(cond, TriesCond):
        return {"kind": "tries", "n": cond.n}
    if isinstance(cond, IdleCond):
        return {"kind": "idle", "seconds": cond.seconds}
    if isinstance(cond, CmdCond):
        return {"kind": "cmd", "base": cond.base,
                "has": list(cond.has), "missing": list(cond.missing)}
    if isinstance(cond, OutputCond):
        return {"kind": "output", "substr": cond.substr}
    msg = f"unknown condition: {cond!r}"
    raise TypeError(msg)


def _cond_from_dict(data: dict) -> Condition:
    kind = data["kind"]
    if kind == "tries":
        return TriesCond(data["n"])
    if kind == "idle":
        return IdleCond(data["seconds"])
    if kind == "cmd":
        return CmdCond(data["base"], tuple(data["has"]), tuple(data["missing"]))
    if kind == "output":
        return OutputCond(data["substr"])
    msg = f"unknown condition kind: {kind!r}"
    raise ValueError(msg)


def _hint_to_dict(hint: HintRule) -> dict:
    return {"condition": _cond_to_dict(hint.condition), "action": _action_to_dict(hint.action)}


def _hint_from_dict(data: dict) -> HintRule:
    return HintRule(condition=_cond_from_dict(data["condition"]),
                    action=_action_from_dict(data["action"]))


def _voice_to_dict(voice: Voice) -> dict:
    return {"hello": [_action_to_dict(a) for a in voice.hello],
            "bye": [_action_to_dict(a) for a in voice.bye]}


def _voice_from_dict(data: dict) -> Voice:
    return Voice(hello=tuple(_action_from_dict(a) for a in data.get("hello", [])),
                 bye=tuple(_action_from_dict(a) for a in data.get("bye", [])))


def _settings_to_dict(settings: Settings) -> dict:
    return {"type_mode": settings.type_mode, "type_speed": settings.type_speed,
            "pager": settings.pager, "user": settings.user, "sudo": settings.sudo}


def _settings_from_dict(data: dict) -> Settings:
    return Settings(user=data.get("user", "student"),
                    sudo=data.get("sudo", True),
                    type_mode=data.get("type_mode", "normal"),
                    type_speed=data.get("type_speed", 45),
                    pager=data.get("pager", False))


def _stage_to_dict(stage: StageMeta) -> dict:
    return {
        "message": stage.message,
        "neutral": list(stage.neutral),
        "check": stage.check,
        "on_enter": [_action_to_dict(a) for a in stage.on_enter],
        "on_pass": [_action_to_dict(a) for a in stage.on_pass],
        "acceptance": stage.acceptance,
        "hints": [_hint_to_dict(h) for h in stage.hints],
    }


def _stage_from_dict(data: dict) -> StageMeta:
    return StageMeta(
        message=data["message"],
        neutral=tuple(data["neutral"]),
        check=data["check"],
        on_enter=tuple(_action_from_dict(a) for a in data["on_enter"]),
        on_pass=tuple(_action_from_dict(a) for a in data["on_pass"]),
        acceptance=data["acceptance"],
        hints=tuple(_hint_from_dict(h) for h in data.get("hints", [])),
    )


def meta_to_dict(meta: TaskMeta) -> dict:
    """Serialize TaskMeta to a JSON-ready dict."""
    return {
        "image_ref": meta.image_ref,
        "stages": [_stage_to_dict(s) for s in meta.stages],
        "readme": meta.readme,
        "voice": _voice_to_dict(meta.voice),
        "settings": _settings_to_dict(meta.settings),
        "react": [_action_to_dict(a) for a in meta.react],
    }


def meta_from_dict(data: dict) -> TaskMeta:
    """Rebuild TaskMeta from its JSON dict."""
    return TaskMeta(
        image_ref=data["image_ref"],
        stages=tuple(_stage_from_dict(s) for s in data["stages"]),
        readme=data.get("readme"),
        voice=_voice_from_dict(data.get("voice", {})),
        settings=_settings_from_dict(data.get("settings", {})),
        react=tuple(_action_from_dict(a) for a in data.get("react", [])),
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
