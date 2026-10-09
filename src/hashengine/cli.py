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
    parser = argparse.ArgumentParser(
        prog="hashengine",
        description="Сборка, публикация и запуск пула заданий hashpass (для авторов).")
    parser.add_argument("--no-update", action="store_true",
                        help="не обновляться при запуске (иначе ставится свежий main с GitHub)")
    sub = parser.add_subparsers(dest="command")
    p_build = sub.add_parser("build", help="собрать образ/задание из Taskfile")
    p_build.add_argument("taskfile")
    p_build.add_argument("-t", "--tag", help="имя[:версия] (переопределяет строку image в Taskfile)")
    p_push = sub.add_parser("push", help="отправить образ/задание на пул")
    p_push.add_argument("ref", help="образ/задание, или `base` — базовый образ этого runtime")
    p_push.add_argument("registry", nargs="?", help="адрес пула (по умолчанию — сохранённый)")
    p_push.add_argument("--task", action="store_true",
                        help="добавить задание в каталог (номер назначится автоматически)")
    p_push.add_argument("--force", action="store_true",
                        help="перезаписать образ на пуле, даже если ref уже там "
                             "(нужно, чтобы залить чистый слой поверх контаминированного)")
    p_serve = sub.add_parser("serve", help="запустить пул (реестр + веб)")
    p_serve.add_argument("--host", help="адрес привязки (по умолчанию 127.0.0.1 или $HASHPASS_REGISTRY; "
                         "0.0.0.0 — открыть пул наружу)")
    p_serve.add_argument("--port", type=int, help="порт (по умолчанию 8080 или $HASHPASS_REGISTRY)")
    p_serve.add_argument("--tls-cert", help="TLS-сертификат (PEM) → работать по HTTPS")
    p_serve.add_argument("--tls-key", help="приватный TLS-ключ (PEM), вместе с --tls-cert")
    p_serve.add_argument("--tls-self-signed", action="store_true",
                         help="сгенерировать и использовать самоподписанный сертификат (нужен openssl)")
    p_serve.add_argument("--reset-admin", action="store_true",
                         help="перегенерировать пароль администратора при старте и вывести его")
    p_login = sub.add_parser("login", help="вход на пул (запросит логин + пароль)")
    p_login.add_argument("registry", nargs="?", help="адрес пула (по умолчанию — сохранённый)")
    p_login.add_argument("--if-needed", action="store_true",
                         help="ничего не спрашивать, если токен уже в кэше (для скриптов/deploy.sh)")
    p_logout = sub.add_parser("logout", help="выйти с пула (забыть токен, оставить адрес)")
    p_logout.add_argument("registry", nargs="?", help="адрес пула (по умолчанию — сохранённый)")
    p_pull = sub.add_parser("pull", help="подтянуть образ/задание с пула")
    p_pull.add_argument("ref")
    p_pull.add_argument("registry", nargs="?", help="адрес пула (по умолчанию — сохранённый)")
    sub.add_parser("images", help="список локально собранных образов и заданий")
    p_cat = sub.add_parser("catalog", help="каталог пула: раскладка по блокам (администратор)")
    p_cat.add_argument("action", choices=["layout"], help="layout — задать блоки и порядок")
    p_cat.add_argument("specs", nargs="+", metavar="'Название: ref ref …'",
                       help="блоки по порядку; ref без namespace получает ваш логин")
    p_cat.add_argument("--registry", help="адрес пула (по умолчанию — сохранённый)")
    p_remote = sub.add_parser("remote", help="список образов/заданий на пуле")
    p_remote.add_argument("registry", nargs="?", help="адрес пула (по умолчанию — сохранённый)")
    return parser


def _dispatch(env: cli.Home, args: argparse.Namespace) -> int:  # noqa: PLR0911, C901
    """Route a parsed engine sub-command (no sub-command prints help)."""
    command = args.command
    if command is None:
        build_parser().print_help()
        return 0
    if command == "build":
        return cli.cmd_build(env, args.taskfile, args.tag)
    if command == "push":
        if args.ref == "base":
            return cli.cmd_push_base(env, args.registry, force=args.force)
        return cli.cmd_push(env, args.ref, args.registry, publish=args.task, force=args.force)
    if command == "serve":
        return cli.cmd_serve(env, args.host, args.port, certfile=args.tls_cert,
                             keyfile=args.tls_key, self_signed=args.tls_self_signed,
                             reset_admin=args.reset_admin)
    if command == "login":
        return cli.cmd_login(env, args.registry, if_needed=args.if_needed)
    if command == "logout":
        return cli.cmd_logout(env, args.registry)
    if command == "pull":
        return cli.cmd_pull(env, args.ref, args.registry)
    if command == "remote":
        return cli.cmd_remote_images(env, args.registry)
    if command == "catalog":
        return cli.cmd_catalog_layout(env, args.specs, args.registry)
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
