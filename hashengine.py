#!/bin/python3.13

import os
import sys
import argparse

from hashpass.engine import print_images, new, pull, push, send_statistic, delete, edit, create, play, remote


def main():
    # Проверка, запущена ли программа с правами суперпользователя
    if os.geteuid() != 0:
        print("Эта программа должна быть запущена с правами суперпользователя. Используйте 'sudo'.")
        sys.exit(1)  # Завершение программы с кодом 1 (ошибка)

    cmds = {
        'images': print_images,
        'new': new,
        'pull': pull,
        'push': push,
        'delete': delete, 'remove': delete, 'rm': delete, 'del': delete,
        'edit': edit,
        'create': create,
        'play': play, 'start': play,
        'remote': remote
    }

    parser = argparse.ArgumentParser(description='hashengine.py')
    parser.add_argument('cmd', nargs='?', default='images', choices=cmds.keys(), help='cmd of hashengine')
    parser.add_argument('args', nargs=argparse.REMAINDER, help='args of cmd')
    pargs = parser.parse_args()

    cmds[pargs.cmd](*pargs.args)


if __name__ == "__main__":
    main()


