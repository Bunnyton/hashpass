"""
`hashengine` -- the old name of the author's commands, now one `hashpass` binary (spec 2026-10-23 §1).

Kept as an alias so nothing that still says `hashengine` breaks: `hashengine <args>` is
`hashpass <args>` (same arguments, same exit code), `hashengine` alone is `hashpass work`. The prod
pool runs `python3 -m hashengine serve` and its self-update restarts the same module, so this must
keep working until every pool is started as `hashpass serve`.
"""
import sys
from collections.abc import Sequence

from hashpass.author_cli import say_moved
from hashpass.student_cli import build_parser
from hashpass.student_cli import main as hashpass_main


def main(argv: Sequence[str] | None = None) -> int:
    """Run the same `hashpass` command (a bare `hashengine` opens the work screen)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not any(not a.startswith("-") for a in args) and "-h" not in args and "--help" not in args:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):   # no terminal: no work screen
            say_moved("--help")
            build_parser().print_help()
            return 0
        args.append("work")
    say_moved(" ".join(a for a in args if a != "--no-update"))
    return hashpass_main(args)
