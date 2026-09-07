"""hashpass student CLI: run, list, pull, login over hashpass.cli (authoring lives in hashengine)."""
import argparse
from collections.abc import Sequence

from hashpass import cli


def build_parser() -> argparse.ArgumentParser:
    """Construct the student parser: run, list, pull, login (no sub-command → task picker)."""
    parser = argparse.ArgumentParser(prog="hashpass", description="Run hashpass tasks.")
    sub = parser.add_subparsers(dest="command")
    p_run = sub.add_parser("run", help="run a task (interactive) or a bare image (shell)")
    p_run.add_argument("ref")
    sub.add_parser("list", help="list available tasks and images")
    p_pull = sub.add_parser("pull", help="pull an image/task from a registry")
    p_pull.add_argument("ref")
    p_pull.add_argument("registry")
    p_login = sub.add_parser("login", help="log in to a registry (caches a token)")
    p_login.add_argument("registry")
    p_login.add_argument("-u", "--user")
    return parser


def _dispatch(env: cli.Home, args: argparse.Namespace) -> int:
    """Route a parsed student sub-command (no sub-command → interactive task picker)."""
    command = args.command
    if command is None:
        return cli.task_mode(env)
    if command == "run":
        return cli.cmd_run(env, args.ref)
    if command == "list":
        return cli.cmd_images(env)
    if command == "pull":
        return cli.cmd_pull(env, args.ref, args.registry)
    return cli.cmd_login(env, args.registry, args.user)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse args and dispatch under the shared error boundary."""
    return cli.run_main(build_parser(), _dispatch, argv)
