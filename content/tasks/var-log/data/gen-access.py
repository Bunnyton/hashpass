#!/usr/bin/env python3
"""Журнал доступа nginx для задания var-log (детерминированно, seed 7).

Вечер 2 ноября — утро 3-го. Обычные посетители (≈40 адресов 10.20.x.x) ходят по страницам
и получают 200/304. Ночью (≈01:00–04:00) сайт перебирают сканеры: 23 адреса из сетей для
документации, каждый пробует типичные «дыры» по нескольку раз и получает 404. Других 404 в
журнале нет. Ответ шага — 23 уникальных адреса.
Запуск: python3 data/gen-access.py > data/nginx/access.log
"""
import random
from datetime import datetime, timedelta

random.seed(7)
visitors = sorted({f"10.20.{random.randint(1, 9)}.{random.randint(2, 250)}" for _ in range(40)})
scanners = sorted({f"{net}.{random.randint(2, 250)}"
                   for net in ("203.0.113", "198.51.100", "192.0.2") for _ in range(8)})[:23]
pages = ["/", "/index.html", "/news/", "/news/2026-10-28.html", "/contacts.html", "/price.pdf",
         "/css/site.css", "/js/app.js", "/img/logo.png", "/zayavka.html", "/favicon.ico"]
agents = ["Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36",
          "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"]
probes = ["/wp-login.php", "/wp-admin/", "/.env", "/.git/config", "/phpmyadmin/", "/admin.php",
          "/xmlrpc.php", "/config.php.bak", "/backup.zip", "/server-status", "/.aws/credentials",
          "/vendor/phpunit/phpunit/src/Util/PHP/eval-stdin.php", "/cgi-bin/luci", "/boaform/admin/formLogin"]
night_from, night_to = datetime(2026, 11, 3, 1, 0), datetime(2026, 11, 3, 4, 0)
t = datetime(2026, 11, 2, 19, 0, 0)
lines = []
while t < datetime(2026, 11, 3, 9, 0):
    t += timedelta(seconds=random.randint(5, 60))
    stamp = t.strftime("%d/%b/%Y:%H:%M:%S +0300")
    if night_from <= t < night_to and random.random() < 0.8:
        ip, path, code, size = random.choice(scanners), random.choice(probes), 404, 162
        agent = "Mozilla/5.0 zgrab/0.x"
    else:
        ip, path = random.choice(visitors), random.choice(pages)
        code = random.choice([200, 200, 200, 200, 304])
        size = 0 if code == 304 else random.randint(400, 48000)
        agent = random.choice(agents)
    lines.append(f'{ip} - - [{stamp}] "GET {path} HTTP/1.1" {code} {size} "-" "{agent}"')
print("\n".join(lines))
