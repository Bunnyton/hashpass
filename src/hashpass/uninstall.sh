#!/usr/bin/env bash
# hashpass -- uninstall. Removes what the online and the offline installers put in:
#
#   curl -fsSL <pool>/uninstall.sh | bash        (works even when `hashpass` itself is broken)
#   hashpass uninstall
#
# Add `-y` (`| bash -s -- -y`) to skip the question. Run it as the user who installed hashpass.
# Distro packages the installer asked for (python3.13, git, systemd-container, qemu) stay: other
# programs may use them. The account and the progress live on the pool and stay there too.
set -euo pipefail

say() { printf '%s\n' "$*"; }
die() { printf 'hashpass: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" != 0 ] || die "запустите от своего пользователя, без sudo: hashpass живёт в его домашнем каталоге"

HP="${HASHPASS_HOME:-$HOME/.hashpass}"
APP="$HOME/.local/share/hashpass"            # the offline install's own Python
BIN="$HOME/.local/bin"
SYS=/opt/hashpass-sys                        # the offline install's systemd-nspawn & co
PORT=47080                                   # the offline install's local pool

TTY=/dev/tty; ( : </dev/tty ) 2>/dev/null || TTY=""
if [ "${1:-}" != "-y" ]; then
  [ -n "$TTY" ] || die "нет терминала, чтобы спросить; удалить без вопроса: bash -s -- -y"
  say "Будет удалено:"
  say "  команды hashpass и hashengine;"
  say "  $HP -- скачанные задания, собранные образы, настройки;"
  say "  строка PATH hashpass в ~/.bashrc, ~/.profile, ~/.zshrc."
  if [ -d "$SYS" ]; then say "  $SYS -- systemd-nspawn офлайн-установки (sudo спросит пароль)."; fi
  printf 'Удалить? [y/N] '
  read -r ans <"$TTY" || ans=""
  case "$ans" in y|Y|yes|д|Д|да) ;; *) say "Отменено, ничего не удалено."; exit 1 ;; esac
fi

# --- running consoles and the local pool of THIS user ---------------------------------------------
# a console is the machine hp-<pid>-<hex> of a hashpass process; other users' consoles stay
if command -v machinectl >/dev/null 2>&1; then
  for m in $(machinectl list --no-legend 2>/dev/null | awk '$1 ~ /^hp-[0-9]+-/ {print $1}'); do
    pid="${m#hp-}"; pid="${pid%%-*}"
    if [ "$(stat -c %u "/proc/$pid" 2>/dev/null)" = "$(id -u)" ]; then
      say "останавливаю консоль $m"
      sudo machinectl terminate "$m" || true
    fi
  done
fi
for d in /proc/[0-9]*; do
  [ "$(stat -c %u "$d" 2>/dev/null)" = "$(id -u)" ] || continue
  if tr '\0' ' ' < "$d/cmdline" 2>/dev/null | grep -q -- "-m hashpass --no-update serve --host 127.0.0.1 --port $PORT"; then
    kill "${d#/proc/}" 2>/dev/null || true
  fi
done

# --- the commands -----------------------------------------------------------------------------------
if [ -x "$BIN/hashpass" ] && [ ! -L "$BIN/hashpass" ]; then
  # the online install: `pip install --user` with the interpreter its shebang names
  PY="$(head -1 "$BIN/hashpass" | sed -n 's/^#! *//p' | awk '{print $1}')"
  if [ -n "$PY" ] && "$PY" -m pip --version >/dev/null 2>&1; then
    BSP=""
    "$PY" -m pip uninstall --help 2>/dev/null | grep -q -- --break-system-packages && BSP="--break-system-packages"
    # shellcheck disable=SC2086  # $BSP is empty or one flag
    "$PY" -m pip uninstall -y $BSP hashpass >/dev/null 2>&1 || true
  fi
fi
rm -f "$BIN/hashpass" "$BIN/hashengine"
rm -rf "$APP"

# --- PATH lines the installers added ------------------------------------------------------------
for rc in "$HOME/.bashrc" "$HOME/.profile" "$HOME/.zshrc"; do
  if [ -f "$rc" ]; then sed -i '/;; esac  # hashpass$/d' "$rc"; fi
done
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/hashpass.fish"

# --- ~/.hashpass: images were unpacked through sudo, so root owns part of it ------------------
if [ -e "$HP" ]; then
  # a console left mounted (killed run): unmount first, never delete through a live mount
  { findmnt -rn -o TARGET | grep -F "$HP/" || true; } | sort -r | while read -r m; do
    sudo umount "$m" 2>/dev/null || sudo umount -l "$m" 2>/dev/null || true
  done
  if findmnt -rn -o TARGET | grep -qF "$HP/"; then
    die "под $HP ещё что-то смонтировано -- перезагрузите машину и запустите удаление снова"
  fi
  say "удаляю $HP"
  sudo rm -rf --one-file-system "$HP"
fi

# --- the offline install's system part ------------------------------------------------------------
if [ -d "$SYS" ]; then
  say "удаляю $SYS"
  for l in /usr/local/bin/* /usr/bin/systemd-nspawn /usr/bin/machinectl /usr/bin/rsync; do
    if [ -L "$l" ]; then
      case "$(readlink "$l")" in "$SYS"/*) sudo rm -f "$l" ;; esac
    fi
  done
  if grep -qs "$SYS" /etc/systemd/system/systemd-machined.service; then
    sudo systemctl disable --now --quiet systemd-machined.service || true
    sudo rm -f /etc/systemd/system/systemd-machined.service \
               /etc/dbus-1/system.d/org.freedesktop.machine1.conf
    sudo systemctl daemon-reload
  fi
  sudo rm -rf "$SYS"
fi
if [ -f /etc/sysctl.d/60-hashpass.conf ]; then sudo rm -f /etc/sysctl.d/60-hashpass.conf; fi

say "hashpass удалён. Аккаунт и прогресс остались на пуле -- после новой установки всё вернётся."
say "Системные пакеты, которые ставил установщик (python3.13, git, systemd-container), не тронуты."
