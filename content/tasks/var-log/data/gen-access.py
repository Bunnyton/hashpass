#!/usr/bin/env python3
"""Журнал доступа nginx для задания var-log (детерминированно, seed 7).

Обычные посетители (≈15 адресов) ходят по страницам сайта и получают 200/304; сканер
203.0.113.66 перебирает типичные «дыры» и получает только 404. Других 404 в журнале нет.
Запуск: python3 data/gen-access.py > data/nginx/access.log
"""
import random
from datetime import datetime, timedelta

random.seed(7)
visitors = [f"10.20.{random.randint(1, 9)}.{random.randint(2, 250)}" for _ in range(15)]
pages = ["/", "/index.html", "/news/", "/news/2026-10-28.html", "/contacts.html", "/price.pdf",
         "/css/site.css", "/js/app.js", "/img/logo.png", "/zayavka.html", "/favicon.ico"]
agents = ["Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36",
          "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"]
probes = ["/wp-login.php", "/wp-admin/", "/.env", "/.git/config", "/phpmyadmin/", "/admin.php",
          "/xmlrpc.php", "/config.php.bak", "/backup.zip", "/server-status", "/.aws/credentials",
          "/vendor/phpunit/phpunit/src/Util/PHP/eval-stdin.php", "/cgi-bin/luci", "/boaform/admin/formLogin"]
t = datetime(2026, 11, 3, 6, 0, 0)
lines = []
for i in range(640):
    t += timedelta(seconds=random.randint(5, 140))
    stamp = t.strftime("%d/%b/%Y:%H:%M:%S +0300")
    if 300 < i < 380 and random.random() < 0.85:
        ip, path, code, size = "203.0.113.66", random.choice(probes), 404, 162
        agent = "Mozilla/5.0 zgrab/0.x"
    else:
        ip, path = random.choice(visitors), random.choice(pages)
        code = random.choice([200, 200, 200, 200, 304])
        size = 0 if code == 304 else random.randint(400, 48000)
        agent = random.choice(agents)
    lines.append(f'{ip} - - [{stamp}] "GET {path} HTTP/1.1" {code} {size} "-" "{agent}"')
print("\n".join(lines))
