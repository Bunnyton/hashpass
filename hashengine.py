#!/bin/python3.13

import os
import sys

from hashpass.engine import print_images, new, pull, push, send_statistic, delete, edit, create, play


def main():
    try:
        # Проверка, запущена ли программа с правами суперпользователя
        if os.geteuid() != 0:
            print("Эта программа должна быть запущена с правами суперпользователя. Используйте 'sudo'.")
            sys.exit(1)  # Завершение программы с кодом 1 (ошибка)

        sys.argv.pop(0)

        if len(sys.argv) == 0:
            print_images()

        elif sys.argv[0] == "new":
            new(*sys.argv[1::])

        elif sys.argv[0] == "pull":
            pull(*sys.argv[1::])

        elif sys.argv[0] == "push":
            push(*sys.argv[1::])

        elif sys.argv[0] == "send":
            send_statistic(*sys.argv[1::])

        elif sys.argv[0] == "rm" or sys.argv[0] == "remove" or sys.argv[0] == "del" or sys.argv[0] == "delete":
            delete(*sys.argv[1::])

        elif sys.argv[0] == "edit":
            edit(*sys.argv[1::])

        elif sys.argv[0] == "create":
            create(*sys.argv[1::])

        elif sys.argv[0] == "start" or sys.argv[0] == "play":
            play(*sys.argv[1::])

        # elif sys.argv[0] == "rename": #FIXME change to tag
        #     rename(sys.argv[1::])

        else:
            raise Exception("Incorrect command")


    except Exception as e:
        raise
        print(' '.join(['❌' , str(e)]))


if __name__ == "__main__":
    main()


