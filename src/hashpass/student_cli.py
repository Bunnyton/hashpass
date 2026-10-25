"""hashpass student CLI: register/login on the pool, pull tasks, run them (no authoring)."""
import argparse
import sys
from collections.abc import Sequence

from hashpass import cli, my_courses, uninstall, version
from hashpass.author_cli import add_author_commands, dispatch_author
from hashpass.emulation import ensure_x86_emulation
from hashpass.sudo import ensure_sudo

_NEEDS_SUDO = (None, "run", "pull")   # these unpack/run containers via `sudo …`


def build_parser() -> argparse.ArgumentParser:
    """Build the one `hashpass` parser: courses for students + build/push/clone/serve for authors."""
    parser = argparse.ArgumentParser(prog="hashpass",
                                     description="Курсы, задания и образы hashpass: проходить, "
                                                 "собирать, публиковать.")
    parser.add_argument("--version", action="version",
                        version=f"hashpass {version.__version__}")
    parser.add_argument("--no-update", action="store_true",
                        help="не обновляться при запуске (иначе ставится свежий main с GitHub)")
    sub = parser.add_subparsers(dest="command", metavar="<команда>")
    p_reg = sub.add_parser("register", help="регистрация на пуле (логин и пароль)")
    p_reg.add_argument("--pool", help="адрес пула (иначе $HASHPASS_POOL или сохранённый)")
    p_login = sub.add_parser("login", help="вход на пул")
    p_login.add_argument("registry", nargs="?", help="адрес пула (по умолчанию — сохранённый)")
    p_login.add_argument("--pool", help="адрес пула (иначе $HASHPASS_POOL или сохранённый)")
    p_login.add_argument("--if-needed", action="store_true",
                         help="ничего не спрашивать, если уже вошли (для скриптов)")
    p_logout = sub.add_parser("logout", help="выйти с пула (забыть токен, оставить адрес)")
    p_logout.add_argument("registry", nargs="?", help=argparse.SUPPRESS)
    p_logout.add_argument("--pool", help="адрес пула (иначе $HASHPASS_POOL или сохранённый)")
    p_pull = sub.add_parser("pull", help="без аргумента — задания текущего курса; с ref — образ/задание")
    p_pull.add_argument("ref", nargs="?", help="образ или задание на пуле, например alice/lab:1")
    p_pull.add_argument("registry", nargs="?", help="адрес пула (по умолчанию — сохранённый)")
    p_run = sub.add_parser("run", help="запустить: номер или задание курса — с зачётом; "
                                       "другой образ — без зачёта")
    p_run.add_argument("task", help="номер в курсе (напр. 1) или ref (имя:тег)")
    p_run.add_argument("registry", nargs="?", help="адрес пула (по умолчанию — сохранённый)")
    p_sol = sub.add_parser("solution", help="показать своё решение задания (команды и вывод)")
    p_sol.add_argument("task", help="номер из каталога (напр. 1) или ref (имя:версия)")
    p_add = sub.add_parser("add", help="добавить курс: ссылка со страницы курса или владелец/курс")
    p_add.add_argument("link", help="ссылка вида https://<пул>/c/<владелец>/<курс>")
    p_search = sub.add_parser("search", help="найти курсы, задания и образы — на пуле и здесь: hashpass search git")
    p_search.add_argument("query", nargs="?", default="", help="что искать (пусто — всё)")
    p_courses = sub.add_parser("courses", help="мои курсы; с именем — сделать курс текущим")
    p_courses.add_argument("course", nargs="?", help="владелец/курс")
    p_cfg = sub.add_parser("config", help="показать/задать настройки (адрес пула)")
    cfg_sub = p_cfg.add_subparsers(dest="config_key")
    p_cfg_pool = cfg_sub.add_parser("pool", help="показать или задать адрес пула")
    p_cfg_pool.add_argument("url", nargs="?", help="новый адрес пула (без него — показать текущий)")
    p_un = sub.add_parser("uninstall", help="удалить hashpass с этой машины (аккаунт на пуле останется)")
    p_un.add_argument("-y", "--yes", action="store_true", help="не спрашивать подтверждения")
    add_author_commands(sub)
    # argparse lists a SUPPRESSed sub-command as «==SUPPRESS==» -- drop it from the help instead
    sub._choices_actions = [a for a in sub._choices_actions if a.help != argparse.SUPPRESS]  # noqa: SLF001
    return parser


def _dispatch(env: cli.Home, args: argparse.Namespace) -> int:   # noqa: PLR0911, PLR0912, C901
    """Route a parsed student sub-command (no sub-command → pool home: pull + list)."""
    command = args.command
    if command == "uninstall":                    # before the local pool starts or courses load
        return uninstall.run(yes=args.yes)
    if isinstance(env, cli.Home) and command != "serve":   # an offline install: its own pool
        cli.ensure_local_pool(env)
    if isinstance(env, cli.Home):                 # tasks come through the current course
        my_courses.activate(env.root, cli._pool_url(env) or "")   # noqa: SLF001
    if command in _NEEDS_SUDO:   # ask for the password HERE, in the plain terminal, not under the TUI
        say = lambda s: (sys.stdout.write(s), sys.stdout.flush())  # noqa: E731
        ensure_sudo(say)
        ensure_x86_emulation(say)    # an ARM machine runs the x86_64 images through qemu
    if command is None:
        return cli.cmd_pool_home(env)
    authored = dispatch_author(env, args)
    if authored is not None:
        return authored
    if command == "register":
        return cli.cmd_register(env, args.pool)
    if command == "login":
        if args.if_needed:
            return cli.cmd_login(env, args.registry or args.pool, if_needed=True)
        return cli.cmd_pool_login(env, args.registry or args.pool)
    if command == "logout":
        return cli.cmd_logout(env, args.registry or args.pool)
    if command == "pull":
        if args.ref:
            return cli.cmd_pull(env, args.ref, args.registry)
        return cli.cmd_pool_pull(env)
    if command == "solution":
        return cli.cmd_solution(env, args.task)
    if command == "config":
        return cli.cmd_config_pool(env, getattr(args, "url", None))
    if command == "add":
        return cli.cmd_course_add(env, args.link)
    if command == "courses":
        return cli.cmd_courses(env, args.course)
    if command == "search":
        return cli.cmd_course_search(env, args.query)
    return cli.cmd_run_any(env, args.task, args.registry)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse args and dispatch under the shared error boundary."""
    return cli.run_main(build_parser(), _dispatch, argv)
