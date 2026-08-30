"""Harmless orthogonal noise: perturb incidental state without touching observed paths."""

from hashpass.runner.base import Runner


def default_noise() -> list[list[str]]:
    return [
        ["sh", "-c", 'd=$(mktemp -d ./noise.XXXXXX); : > "$d/f"; rm -rf "$d"'],
        ["sh", "-c", "for _ in 1 2 3; do (true &) ; done; wait 2>/dev/null || true"],
    ]


def run_noise(runner: Runner, noise: list[list[str]] | None = None) -> None:
    for cmd in noise if noise is not None else default_noise():
        runner.run(cmd)
