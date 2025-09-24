import os
import sys
import toml
import subprocess

from key import key

from settings import Settings
from userconfig import UserConfig



def ensure_username() -> str:
    while True:
        entered = input("Введите имя пользователя: ").strip()
        if entered:
            return entered

        else:
            print("Имя не может быть пустым. Повторите ввод.")


def main():
    settings = Settings()
    userconfig = UserConfig()

    if not userconfig.username:
        userconfig.save(username=ensure_username(config))

    print(f"Добро пожаловать, {userconfig.username}!\n")

    # --- Режим проверки ---
    if "--check" in sys.argv:
        print("Проверка введённых ключей:\n")
        # сортируем по номеру задания
        for num in sorted(userconfig.tasks.keys(), key=lambda x: int(x)):
            user_key = tasks[num]
            status = "✅ верно" if user_key == key(settings.settings.masterkey, userconfig.username, num) else f"❌ неверно)"

            print(f"Задание {num}: {user_key or '—'} -> {status}")
        return

    # --- Основной режим ---
    lt = userconfig.get_last_task_num()

    while True:
        try:
            choice = input(f"Введите номер задания (Enter = продолжить с {lt}): ").strip()
            task_num = lt 
            if choice != "": 
                task_num = int(choice)

            break
        except Exception:
            print("Задание недоступно")


    while True:
        
        if task_num == 0 or key(settings.masterkey, userconfig.username, task_num) == userconfig.get_key(task_num):
                # Запуск задания
            subprocess.run(['/'.join([settings.sys_app_path]), "start", "bunnyton/" + str(task_num)])

        else:
            while True:
                user_key = input("Введите ключ (Ctrl+C = выход): ").strip()

                if user_key == key(settings.masterkey, userconfig.username, task_num):
                    userconfig.save(key=user_key, task_num=task_num)
                    break
                else:
                    print("❌ Неверный ключ.")
                    continue


        while True:
            user_key = input("Введите ключ, чтобы перейти к следующему заданию (Ctrl+C = выход): ").strip()

            if user_key == key(settings.masterkey, userconfig.username, task_num + 1):
                userconfig.save(key=user_key, task_num=task_num + 1)
                break
            else:
                print("❌ Неверный ключ.")
                # не сохраняем, предлагаем попробовать снова на том же задании
                continue


        cont = input("Желаете продолжить? (Enter = да, Ctrl+C = выход): ")
        task_num += 1

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit()
