"""Фотоархив задания bash-loops: python3 mkphotos.py (детерминированно, seed 7).

data/photos/ — 150 снимков «ГГГГ-ММ-ДД Место NNN.JPG» (пробелы в именах), из них 14 уже .jpg;
data/delete.txt — 12 имён на удаление (уже с .jpg — после первого шага все снимки такие).
"""
import random
import shutil
from pathlib import Path

rnd = random.Random(7)
here = Path(__file__).parent / "data"
shutil.rmtree(here, ignore_errors=True)
(here / "photos").mkdir(parents=True)
trips = [("2022-06-18", "Байкал"), ("2022-12-31", "Новый год"), ("2023-05-01", "Дача"),
         ("2023-07-14", "Сочи"), ("2023-09-02", "Свадьба Лены"), ("2024-02-23", "Хибины"),
         ("2024-08-10", "Калининград"), ("2025-01-07", "Рождество у бабушки"),
         ("2025-06-21", "Выпускной"), ("2025-10-04", "Осенний лес")]
names = []
for day, place in trips:
    for n in range(1, 16):
        names.append(f"{day} {place} {n:03d}")
lower = set(rnd.sample(names, 14))
for name in names:
    ext = ".jpg" if name in lower else ".JPG"
    data = bytes(rnd.randrange(256) for _ in range(64))
    (here / "photos" / (name + ext)).write_bytes(b"\xff\xd8\xff\xe0JFIF\x00" + data + b"\xff\xd9")
bad = sorted(rnd.sample(names, 12))
(here / "delete.txt").write_text("".join(f"{n}.jpg\n" for n in bad), encoding="utf-8")
print(len(names), "photos;", len(lower), "already .jpg;", len(bad), "to delete")
