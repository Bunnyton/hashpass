import os
import sys
import toml
import subprocess

from key import key

masterkey = '10383f373f292407117439070130373440255468657365206172652074776f2065787472656d6573206f66207468652073616d6520657373656e63652e'

HASHPASS_DIR = "/opt/.hashpass"
CONFIG_DIR = os.path.join(HASHPASS_DIR, "config")
CONFIG_PATH = '/'.join([CONFIG_DIR, "userconfig.toml"])

# === Работа с конфигом ===
def load_config(path: str) -> dict:
    if not os.path.exists(path):
        dirpath = os.path.dirname(os.path.abspath(path))
        os.makedirs(dirpath, exist_ok=True)
        return {"username": "", "tasks": {}}
    return toml.load(path)

def save_config(path: str, config: dict) -> None:
    # Гарантируем наличие секции tasks
    config.setdefault("tasks", {})
    with open(path, "w", encoding="utf-8") as f:
        toml.dump(config, f)

def ensure_username(config: dict) -> None:
    username = str(config.get("username", "")).strip()
    if not username:
        while True:
            entered = input("Введите имя пользователя: ").strip()
            if entered:
                config["username"] = entered
                save_config(CONFIG_PATH, config)
                print(f"Имя пользователя сохранено: {entered}\n")
                break
            else:
                print("Имя не может быть пустым. Повторите ввод.")

def last_task_number(tasks: dict) -> int:
    if not tasks:
        return 0
    # Ключи в TOML в примере строковые: "1", "2", "3"
    # Безопасно приводим к int где возможно
    nums = []
    for k in tasks.keys():
        try:
            nums.append(int(k))
        except ValueError:
            pass
    return max(nums) if nums else 1

def main():
    config = load_config(CONFIG_PATH)
    ensure_username(config)
    tasks = config.setdefault("tasks", {})

    print(f"Добро пожаловать, {config['username']}!\n")

    # --- Режим проверки ---
    if "--check" in sys.argv:
        print("Проверка введённых ключей:\n")
        # сортируем по номеру задания
        for num in sorted(tasks.keys(), key=lambda x: int(x)):
            user_key = tasks[str(num)]
            status = "✅ верно" if user_key == key(masterkey + config['username'] + str(num)) else f"❌ неверно)"

            print(f"Задание {num}: {user_key or '—'} -> {status}")
        return

    # --- Основной режим ---
    lt = last_task_number(tasks)

    while True:
        try:
            choice = input(f"Введите номер задания (Enter = продолжить с {lt}): ")
            task_number = lt if choice == "" else int(choice)
            break
        except Exception:
            pass


    while True:
        if task_number == 0 or tasks.get(str(task_number)) and \
            key(masterkey + config['username'] + str(task_number)) == tasks[str(task_number)]:
                # Запуск задания
            subprocess.run(['/'.join([HASHPASS_DIR, "make_env.py"]), "start", str(task_number) +":latest"])

        else:
            while True:
                user_key = input("Введите ключ (Ctrl+C = выход): ").strip()

                if user_key == key(masterkey + config['username'] + str(task_number)):
                    tasks[str(task_number)] = user_key
                    save_config(CONFIG_PATH, config)  # сохраняем прогресс
                    break
                else:
                    print("❌ Неверный ключ.")
                    # не сохраняем, предлагаем попробовать снова на том же задании
                    continue


        while True:
            user_key = input("Введите ключ, чтобы перейти к следующему заданию (Ctrl+C = выход): ").strip()

            if user_key == key(masterkey + config['username'] + str(task_number + 1)):
                tasks[str(task_number + 1)] = user_key
                save_config(CONFIG_PATH, config)  # сохраняем прогресс
                break
            else:
                print("❌ Неверный ключ.")
                # не сохраняем, предлагаем попробовать снова на том же задании
                continue


        cont = input("Желаете продолжить? (Enter = да, Ctrl+C = выход): ")
        task_number += 1

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit()
