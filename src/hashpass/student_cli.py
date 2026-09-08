"""hashpass student CLI: register/login on the pool, pull tasks, run them (no authoring)."""
import argparse
from collections.abc import Sequence

from hashpass import cli


def build_parser() -> argparse.ArgumentParser:
    """Student parser: register, login, pull, run (no sub-command → pull + list tasks)."""
    parser = argparse.ArgumentParser(prog="hashpass",
                                     description="Register, pull, and run hashpass tasks.")
    sub = parser.add_subparsers(dest="command")
    p_reg = sub.add_parser("register", help="register on the pool (name + group)")
    p_reg.add_argument("--pool", help="pool URL (else $HASHPASS_POOL or the saved one)")
    p_login = sub.add_parser("login", help="log in to the pool")
    p_login.add_argument("--pool", help="pool URL (else $HASHPASS_POOL or the saved one)")
    sub.add_parser("pull", help="pull new/updated tasks from the pool")
    p_run = sub.add_parser("run", help="run a task by catalog number or ref")
    p_run.add_argument("task", help="catalog number (e.g. 1) or a ref (name:version)")
    return parser


def _dispatch(env: cli.Home, args: argparse.Namespace) -> int:
    """Route a parsed student sub-command (no sub-command → pool home: pull + list)."""
    command = args.command
    if command is None:
        return cli.cmd_pool_home(env)
    if command == "register":
        return cli.cmd_register(env, args.pool)
    if command == "login":
        return cli.cmd_pool_login(env, args.pool)
    if command == "pull":
        return cli.cmd_pool_pull(env)
    return cli.cmd_pool_run(env, args.task)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse args and dispatch under the shared error boundary."""
    return cli.run_main(build_parser(), _dispatch, argv)
