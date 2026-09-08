"""hashpass student CLI: register/login on the pool, pull tasks, run them (no authoring)."""
import argparse
from collections.abc import Sequence

from hashpass import cli


def build_parser() -> argparse.ArgumentParser:
    """Student parser: register, login, pull, run (no sub-command → pull + list tasks)."""
    parser = argparse.ArgumentParser(prog="hashpass",
                                     description="Регистрация, загрузка и запуск заданий hashpass.")
    sub = parser.add_subparsers(dest="command")
    p_reg = sub.add_parser("register", help="регистрация на пуле (логин + группа)")
    p_reg.add_argument("--pool", help="адрес пула (иначе $HASHPASS_POOL или сохранённый)")
    p_login = sub.add_parser("login", help="вход на пул")
    p_login.add_argument("--pool", help="адрес пула (иначе $HASHPASS_POOL или сохранённый)")
    sub.add_parser("pull", help="подтянуть новые/обновлённые задания с пула")
    p_run = sub.add_parser("run", help="запустить задание по номеру или ref")
    p_run.add_argument("task", help="номер из каталога (напр. 1) или ref (имя:версия)")
    p_cfg = sub.add_parser("config", help="показать/задать настройки (адрес пула)")
    cfg_sub = p_cfg.add_subparsers(dest="config_key")
    p_cfg_pool = cfg_sub.add_parser("pool", help="показать или задать адрес пула")
    p_cfg_pool.add_argument("url", nargs="?", help="новый адрес пула (без него — показать текущий)")
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
    if command == "config":
        return cli.cmd_config_pool(env, getattr(args, "url", None))
    return cli.cmd_pool_run(env, args.task)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse args and dispatch under the shared error boundary."""
    return cli.run_main(build_parser(), _dispatch, argv)
