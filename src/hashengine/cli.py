"""hashengine CLI: author/server front end (build, push, serve, login, images) over hashpass.cli."""
import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from hashpass import cli

_ENABLE_ENV = "HASHENGINE_ENABLE"
_HOME_ENV = "HASHENGINE_HOME"


def _engine_enabled() -> bool:
    """Whether the author toolkit is activated here (only make install / the pool installer set it)."""
    if os.environ.get(_ENABLE_ENV):
        return True
    home = Path(os.environ.get(_HOME_ENV, Path.home() / ".hashengine"))
    return (home / "engine.enabled").exists()


def build_parser() -> argparse.ArgumentParser:
    """Construct the author/server parser: build, push, serve, login, images."""
    parser = argparse.ArgumentParser(prog="hashengine",
                                     description="Author, build, publish, and serve hashpass tasks.")
    sub = parser.add_subparsers(dest="command")
    p_build = sub.add_parser("build", help="build an image/task from a Taskfile")
    p_build.add_argument("taskfile")
    p_build.add_argument("-t", "--tag", help="name[:version] (overrides the Taskfile's image line)")
    p_push = sub.add_parser("push", help="push an image/task to a registry")
    p_push.add_argument("ref")
    p_push.add_argument("registry")
    p_push.add_argument("--task", type=int, metavar="N",
                        help="publish this task at catalog slot N")
    p_push.add_argument("--title", default="", help="task title shown in the catalog")
    p_serve = sub.add_parser("serve", help="run the pool (registry + web)")
    p_serve.add_argument("--host", help="bind address (default 127.0.0.1 or $HASHPASS_REGISTRY; "
                         "use 0.0.0.0 to expose the pool)")
    p_serve.add_argument("--port", type=int, help="bind port (default 8080 or $HASHPASS_REGISTRY)")
    p_login = sub.add_parser("login", help="log in to a registry (caches a token)")
    p_login.add_argument("registry")
    p_login.add_argument("-u", "--user")
    sub.add_parser("images", help="list built images and tasks")
    return parser


def _dispatch(env: cli.Home, args: argparse.Namespace) -> int:
    """Route a parsed engine sub-command (no sub-command prints help)."""
    command = args.command
    if command is None:
        build_parser().print_help()
        return 0
    if command == "build":
        return cli.cmd_build(env, args.taskfile, args.tag)
    if command == "push":
        return cli.cmd_push(env, args.ref, args.registry, task_number=args.task, title=args.title)
    if command == "serve":
        return cli.cmd_serve(env, args.host, args.port)
    if command == "login":
        return cli.cmd_login(env, args.registry, args.user)
    return cli.cmd_images(env)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse args and dispatch under the shared error boundary (author toolkit must be activated)."""
    if not _engine_enabled():
        sys.stderr.write(
            "hashengine не активирован на этой машине.\n"
            "Это авторский инструмент; поставьте его с сайта пула (нужна роль автора):\n"
            "  curl -fsSL <pool>/install-engine.sh | bash\n"
            "или локально из клона: make install\n")
        return 1
    return cli.run_main(build_parser(), _dispatch, argv)
