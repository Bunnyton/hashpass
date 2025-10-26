#!/usr/bin/env python3
import argparse
import os
import random
import base64
import string
import shutil

# Список возможных расширений файлов
FILE_EXTENSIONS = ["txt", "log", "json", "csv", "xml", "md", "conf", ""]

def random_suffix(length: int = 5) -> str:
    """Возвращает случайную строку для суффикса имени."""
    letters = string.ascii_lowercase + string.digits
    return ''.join(random.choices(letters, k=length))

def generate_random_data() -> str:
    """Генерация случайного содержимого (текст)."""
    size = random.randint(128, 1024)
    data = os.urandom(size)
    encoded = base64.b64encode(data).decode("utf-8")
    return encoded[: random.randint(64, 512)]

def generate_level(base_dir: str, level: int, levels: int, files: int, dirs: int,
                   data_ratio: float, prefix: str, file_prefix: str, dir_prefix: str):
    """Рекурсивное создание структуры директорий и файлов."""
    os.makedirs(base_dir, exist_ok=True)
    print(f"📂 Уровень {level}: {base_dir}")

    # Создание файлов
    for i in range(1, files + 1):
        ext = random.choice(FILE_EXTENSIONS)
        suffix = random_suffix()
        # Если расширения нет — просто без точки
        filename = f"{file_prefix}{level}_{i}_{suffix}" + (f".{ext}" if ext else "")
        file_path = os.path.join(base_dir, filename)

        with open(file_path, "w", encoding="utf-8") as f:
            if random.random() < data_ratio:
                f.write(generate_random_data())

        size = os.path.getsize(file_path)
        status = "(данные)" if size > 0 else "(пустой)"
        print(f"  ├── файл: {filename} {status}")

    # Создание поддиректорий
    if level < levels:
        for j in range(1, dirs + 1):
            suffix = random_suffix()
            dirname = f"{dir_prefix}{level}_{j}_{suffix}"
            subdir = os.path.join(base_dir, dirname)
            generate_level(subdir, level + 1, levels, files, dirs, data_ratio, prefix, file_prefix, dir_prefix)

def main():
    parser = argparse.ArgumentParser(
        prog="generate-tree",
        description="📁 Генератор дерева директорий с настраиваемыми префиксами, уровнями и файлами.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="Пример: generate-tree ./tree -l 3 -f 5 -d 2 -r 0.4 -p test_"
    )

    parser.add_argument("base_dir", help="Базовая директория для генерации.")
    parser.add_argument("-l", "--levels", type=int, default=3, help="Количество уровней директорий.")
    parser.add_argument("-f", "--files", type=int, default=5, help="Количество файлов на уровне.")
    parser.add_argument("-d", "--dirs", type=int, default=2, help="Количество поддиректорий на уровне.")
    parser.add_argument("-r", "--ratio", type=float, default=0.5, help="Доля файлов с данными (0.0–1.0).")
    parser.add_argument("-p", "--prefix", default="", help="Базовый префикс (если указан — используется для файлов и директорий).")
    parser.add_argument("--file-prefix", default=None, help="Префикс для файлов (по умолчанию как --prefix).")
    parser.add_argument("--dir-prefix", default=None, help="Префикс для директорий (по умолчанию как --prefix).")
    parser.add_argument("--clean", action="store_true", help="Очистить базовую директорию перед генерацией.")

    args = parser.parse_args()

    if not (0.0 <= args.ratio <= 1.0):
        parser.error("Параметр --ratio должен быть в диапазоне от 0.0 до 1.0.")

    # Если префиксы не заданы явно — использовать общий
    file_prefix = args.file_prefix if args.file_prefix is not None else args.prefix
    dir_prefix = args.dir_prefix if args.dir_prefix is not None else args.prefix

    if args.clean and os.path.exists(args.base_dir):
        print(f"🧹 Очистка {args.base_dir} ...")
        shutil.rmtree(args.base_dir)

    generate_level(args.base_dir, 1, args.levels, args.files, args.dirs, args.ratio, args.prefix, file_prefix, dir_prefix)
    print(f"\n✅ Дерево успешно создано в {args.base_dir}")

if __name__ == "__main__":
    main()

