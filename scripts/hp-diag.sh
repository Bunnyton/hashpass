#!/usr/bin/env bash
# What hashpass needs on this machine, in one report (user 2026-10-23: an ARM VM in UTM).
#
#   curl -fsSL https://raw.githubusercontent.com/Bunnyton/hashpass/main/scripts/hp-diag.sh | bash
#
# Prints every section and keeps a copy in ~/hp-diag.txt. Nothing is changed on the machine;
# `sudo` is asked once, for the kernel log only, and skipped if refused.

out="$HOME/hp-diag.txt"
: > "$out"

section() { printf '\n== %s ==\n' "$1"; }
run() { printf '$ %s\n' "$*"; "$@" 2>&1 || printf '(код выхода %s)\n' "$?"; }

report() {
  section "Система"
  run uname -a
  grep PRETTY_NAME /etc/os-release
  run getconf PAGESIZE

  section "hashpass"
  run command -v hashpass
  python3 -m pip show hashpass 2>/dev/null | head -2 || echo "pip не знает hashpass"
  python3 - <<'PY'
import json
import importlib.metadata as m
try:
    info = json.loads(m.distribution("hashpass").read_text("direct_url.json") or "{}")
    print("установлен из:", info.get("url", "?"))
except Exception:  # noqa: BLE001
    print("пакет hashpass не установлен для этого python3")
PY

  section "systemd-nspawn"
  run systemd-nspawn --version

  section "Эмулятор x86 (binfmt_misc)"
  run ls /proc/sys/fs/binfmt_misc/
  for f in /proc/sys/fs/binfmt_misc/qemu-x86_64 /proc/sys/fs/binfmt_misc/rosetta; do
    if [ -e "$f" ]; then echo "--- $f"; cat "$f"; else echo "--- $f: нет"; fi
  done

  section "qemu"
  dpkg -l 2>/dev/null | grep -Ei 'qemu|binfmt' || echo "пакетов qemu/binfmt нет"
  for q in qemu-x86_64-static qemu-x86_64; do
    if command -v "$q" >/dev/null; then run "$q" --version; else echo "$q: не установлен"; fi
  done

  section "Rosetta"
  mount | grep -i rosetta || echo "Rosetta не смонтирована"

  section "Ядро: падения"
  if sudo dmesg >/dev/null 2>&1 </dev/tty; then
    sudo dmesg | grep -iE 'segfault|qemu|rosetta' | tail -20
  else
    echo "dmesg пропущен (нет sudo)"
  fi

  section "Отчёт hashpass об эмуляции"
  cat "$HOME/hashpass-arm-report.txt" 2>/dev/null || echo "отчёта нет"
}

report 2>&1 | tee "$out"
printf '\nГотово. Пришлите файл %s\n' "$out"
