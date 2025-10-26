#!/bin/python3.13

import os
import sys
import time

from hashpass.key import calc_key
from hashpass.settings import Settings
from hashpass.userconfig import UserConfig
from hashpass.engine import pull, play, send_statistic


settings = Settings()


def ensure_username() -> str:
    while True:
        entered = input("Введите имя пользователя: ").strip()
        if entered:
            return entered

        else:
            print("Имя не может быть пустым. Повторите ввод.")


def check_key(userconfig: UserConfig, task_num: int, key: str=None):
    task_name = userconfig.get_task_name(task_num)
    true_key = calc_key(settings.masterkey, userconfig.username, task_name) 

    if key:
        return true_key == key
    else:
        return true_key == userconfig.get_key(task_num)


def main():
    userconfig = UserConfig()
    if not userconfig.username:
        userconfig.save(username=ensure_username())

    print("\nОбновление списка заданий")
    try:
        pull(*userconfig.get_task_name(all=True), "-l")
        print("Обновление завершено")

    except KeyboardInterrupt:
        print("Обновление прервано пользователем")

    except Exception as e:
        print("Ошибка обновления: ", str(e))


    print(f"\nДобро пожаловать, {userconfig.username}!\n")



        
    # --- Режим проверки ---
    if "--check" in sys.argv:
        print("Проверка введённых ключей:\n")
        # сортируем по номеру задания
        for num in sorted(userconfig.task_progress.keys(), key=lambda x: int(x)):

            status: str
            if check_key(userconfig, task_num=num):
                status = "✅ верно" 

            else:
                status = f"❌ неверно"

            print(f"Задание {num}: {userconfig.get_key(num)} -> {status}")
        return

    # --- Основной режим ---
    task_num: int 
    lt = userconfig.get_last_task_num()

    while True:
        try:
            if lt is None:
                task_num = 0
                print("Рады приветствовать Вас в системе HASHPASS!")
                print("Сейчас Вы перейдете в приветственное задание")
                print("Для входа Вам понадобятся учетные данные student:student\n")
                time.sleep(5)
                print("Удачи!")
                time.sleep(2)

            else:
                choice = input(f"Введите номер задания (Enter = продолжить с {lt + 1}): ").strip()
                task_num = lt + 1
                if choice != "": 
                    task_num = int(choice)

            break

        except Exception:
            print("Задание недоступно")


    while True:
        if task_num == 0 or check_key(userconfig, task_num=task_num - 1):
            # Запуск задания
            try:
                play(userconfig.get_task_name(task_num))

            except Exception as e:
                print(" ".join(["❌", str(e)]))
                return

            while True:
                if check_key(userconfig, task_num=task_num):
                    break

                user_key = ""
                while not user_key:
                    user_key = input("Введите ключ, чтобы перейти к следующему заданию (Ctrl+C = выход): ").strip()

                if check_key(userconfig, task_num=task_num, key=user_key):
                    userconfig.save(key=user_key, task_num=task_num)
                    try:
                        send_statistic()

                    except Exception:
                        pass # Незачем пугать студента какой-то ошибкой
                    break
                
                else:
                    print("❌ Неверный ключ.")
                    # не сохраняем, предлагаем попробовать снова на том же задании
                    continue


            input("Желаете продолжить? (Enter = да, Ctrl+C = выход): ")
            task_num += 1

        else:
            while True:
                user_key = input(f"Введите ключ, полученный в {task_num - 1} задании (Ctrl+C = выход): ").strip()

                if user_key and check_key(userconfig, task_num=task_num - 1, key=user_key):
                    userconfig.save(key=user_key, task_num=task_num - 1)
                    break

                else:
                    print("❌ Неверный ключ.")
                    continue



if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Эта программа должна быть запущена с правами суперпользователя. Используйте 'sudo'.")
        sys.exit(1)  # Завершение программы с кодом 1 (ошибка)

    try:
        main()

    except KeyboardInterrupt:
        sys.exit()
