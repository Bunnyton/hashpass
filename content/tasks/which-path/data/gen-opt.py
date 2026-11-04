#!/usr/bin/env python3
"""Каталог /opt для задания which-path (детерминированно).

Вендор acme поставил целиком в /opt/acme несколько программ: report 2.0 и 2.1 (в каждой —
bin/report и каталоги share/doc/report, lib/report — ловушка для find без -type f), scanner,
sync. Плюс сторонний /opt/vendor-tools. Запуск: python3 data/gen-opt.py data/opt
"""
import os
import random
import sys

random.seed(21)
root = sys.argv[1]
REPORT = """#!/bin/sh
# Acme Report {v} — генератор отчётов
case "$1" in
    --version|-V) echo "report {v}" ;;
    *) echo "report {v}: отчёт за сегодня готов — {n} строк, формат {fmt}" ;;
esac
"""
def put(rel, text="", mode=0o644):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(p, mode)

for v, fmt in (("2.0", "xlsx"), ("2.1", "xlsx и pdf")):
    base = f"acme/report-{v}"
    put(f"{base}/bin/report", REPORT.format(v=v, n=random.randint(100, 900), fmt=fmt), 0o755)
    put(f"{base}/bin/report-export", f"#!/bin/sh\necho 'report-export {v}'\n", 0o755)
    put(f"{base}/etc/report.conf", f"# Acme Report {v}\noutput_dir = /var/lib/report\nlang = ru\n")
    for d in ("share/doc/report", "lib/report"):
        for i in range(random.randint(8, 14)):
            ext = ".so" if d.startswith("lib") else ".txt"
            put(f"{base}/{d}/part{i:02d}{ext}", f"acme report {v} {d} part {i}\n")
    for lang in ("ru", "en", "de", "fr", "kk"):
        put(f"{base}/share/locale/{lang}/LC_MESSAGES/report.mo", f"{lang}\n")
    put(f"{base}/share/man/man1/report.1", f".TH REPORT 1 \"\" \"Acme Report {v}\"\n")
for prog, v in (("scanner", "5.3"), ("sync", "1.8")):
    base = f"acme/{prog}-{v}"
    put(f"{base}/bin/{prog}", f"#!/bin/sh\necho '{prog} {v}'\n", 0o755)
    for d in ("lib", "share/doc", "share/icons", "plugins"):
        for i in range(random.randint(10, 20)):
            put(f"{base}/{d}/{prog}-{d.replace('/', '-')}-{i:02d}.dat", f"{prog} {v} {d} {i}\n")
for i in range(40):
    put(f"vendor-tools/share/templates/template-{i:02d}.xml", f"<template id='{i}'/>\n")
for t in ("backup", "netcheck", "inventory"):
    put(f"vendor-tools/bin/{t}", f"#!/bin/sh\necho '{t} 0.9'\n", 0o755)
