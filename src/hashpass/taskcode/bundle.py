"""Split config bundle: derived checks.json + hand-edited conditions.toml / hints.toml."""
import json
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from hashpass.canon import FileState
from hashpass.taskcode.derive import DerivedChecks, StageChecks
from hashpass.taskcode.model import toml_list, toml_quote

_FILES = ("checks.json", "conditions.toml", "hints.toml")


@dataclass(frozen=True)
class Bundle:
    """A task's logic bundle: derived checks + advisory conditions + interactive hints."""

    checks: DerivedChecks
    conditions: dict
    hints: dict


def _checks_to_dict(checks: DerivedChecks) -> dict:
    return {
        "task_id": checks.task_id,
        "stages": [
            {
                "canonical": {k: {"kind": v.kind, "text": v.text}
                              for k, v in st.canonical.items()},
                "mode": st.mode,
                "threshold": st.threshold,
                "k": st.k,
                "size_threshold": st.size_threshold,
            }
            for st in checks.stages
        ],
    }


def _checks_from_dict(data: dict) -> DerivedChecks:
    stages = tuple(
        StageChecks(
            canonical={k: FileState(v["kind"], v["text"]) for k, v in st["canonical"].items()},
            mode=st["mode"],
            threshold=st["threshold"],
            k=st["k"],
            size_threshold=st["size_threshold"],
        )
        for st in data["stages"]
    )
    return DerivedChecks(task_id=data["task_id"], stages=stages)


def _dump_conditions(conditions: dict) -> str:
    lines: list[str] = []
    for idx in sorted(conditions):
        lines.append(f"[stage.{idx}]")
        for field, values in conditions[idx].items():
            lines.append(f"{field} = {toml_list(tuple(values))}")
        lines.append("")
    return "\n".join(lines)


def _dump_hints(hints: dict) -> str:
    lines: list[str] = []
    for idx in sorted(hints):
        for hint in hints[idx]:
            lines.append(f"[[stage.{idx}]]")
            lines.append(f"trigger = {toml_quote(hint['trigger'])}")
            lines.append(f"message = {toml_quote(hint['message'])}")
            lines.append("")
    return "\n".join(lines)


def _load_stage_keyed(text: str) -> dict:
    data = tomllib.loads(text)
    return {int(idx): value for idx, value in data.get("stage", {}).items()}


def dump_bundle(bundle: Bundle, out_dir: Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "checks.json").write_text(
        json.dumps(_checks_to_dict(bundle.checks), indent=2), encoding="utf-8")
    (out / "conditions.toml").write_text(_dump_conditions(bundle.conditions), encoding="utf-8")
    (out / "hints.toml").write_text(_dump_hints(bundle.hints), encoding="utf-8")


def load_bundle(bundle_dir: Path) -> Bundle:
    d = Path(bundle_dir)
    checks = _checks_from_dict(json.loads((d / "checks.json").read_text(encoding="utf-8")))
    conditions = _load_stage_keyed((d / "conditions.toml").read_text(encoding="utf-8"))
    hints = _load_stage_keyed((d / "hints.toml").read_text(encoding="utf-8"))
    return Bundle(checks=checks, conditions=conditions, hints=hints)


def apply_bundle(bundle_dir: Path, rootfs: Path) -> None:
    dest = Path(rootfs) / ".hash" / ".task"
    dest.mkdir(parents=True, exist_ok=True)
    for name in _FILES:
        shutil.copy2(Path(bundle_dir) / name, dest / name)
