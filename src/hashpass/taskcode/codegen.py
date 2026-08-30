"""Creation mode: turn a recorded command transcript into editable task-as-code."""
from dataclasses import dataclass

from hashpass.taskcode.model import StageCode, TaskCode


@dataclass(frozen=True)
class StageTranscript:
    """Recorded author activity for one stage: commands run + paths changed."""

    commands: tuple[str, ...]
    changed: tuple[str, ...]


def codegen_from_transcript(task_id: str, setup: tuple[str, ...],
                            stages: tuple[StageTranscript, ...]) -> TaskCode:
    """Transform a transcript into TaskCode."""
    stage_codes = tuple(
        StageCode(commands=st.commands, observe=st.changed) for st in stages
    )
    return TaskCode(id=task_id, setup=setup, stages=stage_codes)
