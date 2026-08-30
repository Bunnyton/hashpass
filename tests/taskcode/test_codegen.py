import pytest

from hashpass.taskcode.codegen import StageTranscript, codegen_from_transcript
from hashpass.taskcode.model import StageCode, TaskCode


@pytest.mark.tier1
def test_codegen_from_transcript_builds_taskcode():
    stages = (
        StageTranscript(commands=("echo a > x", "cat x"), changed=("x",)),
        StageTranscript(commands=("echo b > y",), changed=("y",)),
    )
    task = codegen_from_transcript("demo", ("mkdir work",), stages)
    assert task == TaskCode(
        id="demo",
        setup=("mkdir work",),
        stages=(
            StageCode(commands=("echo a > x", "cat x"), observe=("x",)),
            StageCode(commands=("echo b > y",), observe=("y",)),
        ),
    )
