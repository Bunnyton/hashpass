"""Данные задания bash-arrays: python3 mkduty.py (детерминированно, seed 5).

data/duty/team.txt — 7 дежурных «Имя Фамилия»; days.txt — 30 дней декабря;
auth.log — 260 строк «дата время OK|FAIL адрес пользователь», неудачи с 9 адресов.
"""
import datetime
import random
from pathlib import Path

rnd = random.Random(5)
d = Path(__file__).parent / "data" / "duty"
d.mkdir(parents=True, exist_ok=True)
team = ["Анна Петрова", "Борис Сидоров", "Вера Козлова", "Глеб Орлов", "Дина Белова",
        "Егор Смирнов", "Жанна Лебедева"]
(d / "team.txt").write_text("".join(t + "\n" for t in team), encoding="utf-8")
start = datetime.date(2026, 12, 1)
(d / "days.txt").write_text("".join(f"{start + datetime.timedelta(days=i)}\n" for i in range(30)),
                            encoding="utf-8")
bad = [f"203.0.113.{n}" for n in rnd.sample(range(2, 250), 6)] + \
      [f"198.51.100.{n}" for n in rnd.sample(range(2, 250), 3)]
weights = [rnd.randint(1, 60) for _ in bad]
good = ["10.0.0.5", "10.0.0.17", "10.0.0.23"]
users = ["root", "admin", "deploy", "student", "oracle", "test", "git"]
t = datetime.datetime(2026, 11, 3, 0, 0, 0)
lines = []
for _ in range(260):
    t += datetime.timedelta(seconds=rnd.randint(5, 400))
    if rnd.random() < 0.25:
        lines.append(f"{t:%Y-%m-%d %H:%M:%S} OK {rnd.choice(good)} {rnd.choice(['deploy', 'student'])}")
    else:
        ip = rnd.choices(bad, weights)[0]
        lines.append(f"{t:%Y-%m-%d %H:%M:%S} FAIL {ip} {rnd.choice(users)}")
(d / "auth.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
