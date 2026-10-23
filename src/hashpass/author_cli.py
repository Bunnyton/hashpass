"""
Author and pool commands of the one `hashpass` binary (spec 2026-10-23 §1).

They used to be `hashengine`; now they sit next to the student's commands. Where a name meant
two things (`pull`, `run`, `login`), one command does both by its arguments -- see `run_any`.
"""
import argparse
import sys

from hashpass import cli

POOL_HELP = "адрес пула (по умолчанию — сохранённый)"


def add_author_commands(sub: argparse._SubParsersAction) -> None:
    """Add build/push/clone/serve/... to the `hashpass` parser."""
    sub.add_parser("work", help="рабочий экран автора: локальные образы и пул")
    p_build = sub.add_parser("build", help="собрать образ/задание из Taskfile")
    p_build.add_argument("taskfile")
    p_build.add_argument("-t", "--tag", help="имя[:тег] (переопределяет строку image в Taskfile)")
    p_push = sub.add_parser("push", help="отправить новую версию образа/задания на пул "
                                         "(без прав на чужой образ — предложение владельцу)")
    p_push.add_argument("ref", help="образ/задание, или `base` — базовый образ этого runtime")
    p_push.add_argument("registry", nargs="?", help=POOL_HELP)
    p_push.add_argument("-m", "--message", default="", help="что поменялось в этой версии")
    p_push.add_argument("--task", action="store_true", help=argparse.SUPPRESS)   # no longer needed: ignored
    p_push.add_argument("--block", help=argparse.SUPPRESS)
    p_push.add_argument("--force", action="store_true",
                        help="отправить даже без изменений (студенты скачают заново)")
    p_clone = sub.add_parser("clone", help="скачать исходники задания с пула в папку")
    p_clone.add_argument("ref", help="задание на пуле, например alice/lab:1")
    p_clone.add_argument("dest", nargs="?", help="куда (по умолчанию ./<имя задания>)")
    p_clone.add_argument("--registry", help=POOL_HELP)
    p_source = sub.add_parser("source", help=argparse.SUPPRESS)      # the old name of `clone`
    p_source.add_argument("ref")
    p_source.add_argument("dest", nargs="?")
    p_source.add_argument("--registry")
    p_tag = sub.add_parser("tag", help="навесить тег на свою версию на пуле")
    p_tag.add_argument("src", help="версия x:1_v3 или тег x:1 (= последняя)")
    p_tag.add_argument("to", help="новый тег, например stable")
    p_tag.add_argument("--registry", help=POOL_HELP)
    p_rm = sub.add_parser("rm", help="удалить версию с пула (x:1_v3) или локальную копию (--local)")
    p_rm.add_argument("ref")
    p_rm.add_argument("--local", action="store_true", help="удалить только с этой машины")
    p_rm.add_argument("--registry", help=POOL_HELP)
    p_fork = sub.add_parser("fork", help="форкнуть чужое задание в своё пространство имён")
    p_fork.add_argument("src", help="версия или тег, например alice/lab:1")
    p_fork.add_argument("name", nargs="?", help="имя форка (по умолчанию — как у исходного)")
    p_fork.add_argument("--registry", help=POOL_HELP)
    sub.add_parser("images", help="образы и задания на этой машине")
    p_remote = sub.add_parser("remote", help="образы и задания на пуле")
    p_remote.add_argument("registry", nargs="?", help=POOL_HELP)
    p_serve = sub.add_parser("serve", help="запустить пул (реестр + веб)")
    p_serve.add_argument("--host", help="адрес привязки (по умолчанию 127.0.0.1 или $HASHPASS_REGISTRY; "
                                        "0.0.0.0 — открыть пул в сеть)")
    p_serve.add_argument("--port", type=int, help="порт (по умолчанию 8080 или $HASHPASS_REGISTRY)")
    p_serve.add_argument("--tls-cert", help="TLS-сертификат (PEM) → работать по HTTPS")
    p_serve.add_argument("--tls-key", help="приватный TLS-ключ (PEM), вместе с --tls-cert")
    p_serve.add_argument("--tls-self-signed", action="store_true",
                         help="HTTPS с самоподписанным сертификатом (создастся при первом запуске)")
    p_serve.add_argument("--reset-admin", action="store_true",
                         help="сгенерировать новый пароль администратора")
    p_mig = sub.add_parser("migrate-courses", help="перевести этот пул на версии и курсы "
                                                   "(один раз, на машине пула)")
    p_mig.add_argument("--owner", default="bunnyton", help="владелец курса по умолчанию (администратор)")
    p_cat = sub.add_parser("catalog", help=argparse.SUPPRESS)        # a pool not on courses only
    p_cat.add_argument("action", choices=["layout"])
    p_cat.add_argument("specs", nargs="+")
    p_cat.add_argument("--registry")


def dispatch_author(env: cli.Home, args: argparse.Namespace) -> int | None:  # noqa: PLR0911
    """Run an author/pool command; None -- not one of them."""
    command = args.command
    if command == "work":
        from hashengine.tui import run_engine_tui  # noqa: PLC0415
        return run_engine_tui(env)
    if command == "build":
        return cli.cmd_build(env, args.taskfile, args.tag)
    if command == "push":
        if args.ref == "base":
            return cli.cmd_push_base(env, args.registry, force=args.force)
        _say_no_more_flags(args)
        return cli.cmd_push(env, args.ref, args.registry, force=args.force, message=args.message)
    if command in ("clone", "source"):
        return cli.cmd_source(env, args.ref, args.dest, args.registry)
    if command == "serve":
        return cli.cmd_serve(env, args.host, args.port, certfile=args.tls_cert, keyfile=args.tls_key,
                             self_signed=args.tls_self_signed, reset_admin=args.reset_admin)
    if command == "remote":
        return cli.cmd_remote_images(env, args.registry)
    if command == "catalog":
        return cli.cmd_catalog_layout(env, args.specs, args.registry)
    if command == "images":
        return cli.cmd_images(env)
    simple = {
        "tag": lambda: cli.cmd_tag(env, args.src, args.to, args.registry),
        "rm": lambda: cli.cmd_rm(env, args.ref, args.registry, local=args.local),
        "fork": lambda: cli.cmd_fork(env, args.src, args.name, args.registry),
        "migrate-courses": lambda: cli.cmd_migrate_courses(env, args.owner),
    }
    return simple[command]() if command in simple else None


def _say_no_more_flags(args: argparse.Namespace) -> None:
    if args.task or args.block:
        sys.stderr.write("\x1b[2m--task и --block больше не нужны: задание — то, что собрано из "
                         "Taskfile, место в курсе задаётся в вебе.\x1b[0m\n")


def say_moved(old: str) -> None:
    """Tell a `hashengine …` user where the command lives now (once, on stderr)."""
    sys.stderr.write(f"\x1b[2mhashengine больше не нужен — это теперь `hashpass {old}`.\x1b[0m\n")
