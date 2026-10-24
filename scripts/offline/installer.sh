#!/usr/bin/env bash
# hashpass -- offline install. Needs no network: everything is inside this file.
#
#   bash hashpass-offline-x86_64.run
#
# Run it as the user who will solve the tasks (sudo asks for the password where root is needed).
# It puts a standalone Python with hashpass into ~/.local/share/hashpass, the pool's tasks and
# courses into ~/.hashpass (served on 127.0.0.1 by hashpass itself), and -- only when this system
# lacks them -- systemd-nspawn/machinectl/machined/rsync into /opt/hashpass-sys.
set -euo pipefail

PORT=47080                                   # the local pool; pool.json points here
APP="$HOME/.local/share/hashpass"
HOME_HP="${HASHPASS_HOME:-$HOME/.hashpass}"
SYS=/opt/hashpass-sys

say() { printf '%s\n' "$*"; }
die() { printf 'hashpass: %s\n' "$*" >&2; exit 1; }

[ "$(uname -m)" = x86_64 ] || die "этот установщик для x86_64, а процессор $(uname -m)"
[ -d /run/systemd/system ] || die "нужна система с systemd: консоли заданий — машины systemd-nspawn"
if [ "$(id -u)" = 0 ]; then
  SUDO=""
  [ -n "${SUDO_USER:-}" ] && die "запустите без sudo, от своего пользователя: bash $0"
else
  command -v sudo >/dev/null 2>&1 || die "нет sudo: hashpass запускает консоли через sudo"
  SUDO=sudo
fi
command -v tar >/dev/null 2>&1 || die "нет tar"

TMP="$(mktemp -d "${TMPDIR:-/var/tmp}/hashpass-offline.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
say "распаковываю…"
SKIP="$(awk '/^__PAYLOAD_BELOW__$/{print NR + 1; exit}' "$0")"
tail -n +"$SKIP" "$0" | tar -x -C "$TMP"
say "$(head -1 "$TMP/VERSION")"

# --- consoles: systemd-nspawn + machinectl (+ machined), rsync -------------------------------
ours() { [ "$(readlink -f "$(command -v "$1")" 2>/dev/null)" = "$SYS/bin/$1" ]; }   # from an earlier install
NEED=""
for b in systemd-nspawn machinectl rsync; do
  if ! command -v "$b" >/dev/null 2>&1 || ours "$b"; then NEED="$NEED $b"; fi
done
if [ -n "$NEED" ]; then
  say "ставлю в $SYS то, чего нет в системе:$NEED"
  $SUDO rm -rf "$SYS"
  $SUDO mkdir -p "$SYS" /usr/local/bin
  $SUDO cp -r "$TMP/sys/." "$SYS/"
  # run as root through sudo: nobody else may write a byte of it
  $SUDO chown -R 0:0 "$SYS"
  $SUDO chmod -R go-w "$SYS"
  for b in $NEED; do
    $SUDO ln -sf "$SYS/bin/$b" "/usr/local/bin/$b"
    # hashpass runs it as `sudo $b`: a secure_path without /usr/local/bin (Fedora) needs /usr/bin
    $SUDO sh -c "command -v $b" >/dev/null 2>&1 || $SUDO ln -sf "$SYS/bin/$b" "/usr/bin/$b"
  done
fi
if [ -e "$SYS/bin/systemd-machined" ] && [ ! -e /usr/lib/systemd/systemd-machined ] \
   && [ ! -e /lib/systemd/systemd-machined ]; then
  say "служба systemd-machined"
  $SUDO install -m 644 "$SYS/org.freedesktop.machine1.conf" /etc/dbus-1/system.d/org.freedesktop.machine1.conf
  $SUDO install -m 644 "$SYS/systemd-machined.service" /etc/systemd/system/systemd-machined.service
  # the bus reads its policy again (dbus-daemon or dbus-broker), then machined may own its name
  busctl call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus ReloadConfig >/dev/null 2>&1 \
    || $SUDO systemctl reload dbus >/dev/null 2>&1 || $SUDO systemctl reload dbus-broker >/dev/null 2>&1 || true
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --quiet systemd-machined.service
  $SUDO systemctl restart systemd-machined.service       # a re-install brings a new binary
fi
# Many consoles on one machine (a server): each takes ~4 of root's inotify instances (128 by default).
if [ "$(cat /proc/sys/fs/inotify/max_user_instances 2>/dev/null || echo 0)" -lt 8192 ]; then
  say "поднимаю лимит inotify ядра: много консолей hashpass на одной машине"
  $SUDO sh -c 'printf "fs.inotify.max_user_instances = 8192\nfs.inotify.max_user_watches = 1048576\n" > /etc/sysctl.d/60-hashpass.conf && sysctl -q -p /etc/sysctl.d/60-hashpass.conf' \
    || say "не удалось поднять лимит inotify -- не больше ~30 консолей одновременно"
fi

# --- Python + hashpass ------------------------------------------------------------------------
# a pool left running by the previous install serves the old files: stop it (the next launch starts it)
for d in /proc/[0-9]*; do
  [ "$(stat -c %u "$d" 2>/dev/null)" = "$(id -u)" ] || continue
  if tr '\0' ' ' < "$d/cmdline" 2>/dev/null | grep -q -- "-m hashpass --no-update serve --host 127.0.0.1 --port $PORT"; then
    kill "${d#/proc/}" 2>/dev/null || true
  fi
done
say "ставлю Python и hashpass в $APP"
rm -rf "$APP"
mkdir -p "$APP"
tar -xzf "$TMP/python.tar.gz" -C "$APP"
PIP_DISABLE_PIP_VERSION_CHECK=1 "$APP/python/bin/python3" -m pip install --quiet --no-index \
  --no-warn-script-location --find-links "$TMP/wheels" hashpass
BIN="$HOME/.local/bin"
mkdir -p "$BIN"
ln -sf "$APP/python/bin/hashpass" "$BIN/hashpass"
ln -sf "$APP/python/bin/hashengine" "$BIN/hashengine"
PATH_LINE='case ":$PATH:" in *":'"$BIN"':"*) ;; *) export PATH="'"$BIN"':$PATH" ;; esac  # hashpass'
add_line() { mkdir -p "$(dirname "$1")"; grep -qsF "$2" "$1" || printf '\n%s\n' "$2" >> "$1"; }
add_line "$HOME/.bashrc" "$PATH_LINE"
add_line "$HOME/.profile" "$PATH_LINE"
[ -f "$HOME/.zshrc" ] && add_line "$HOME/.zshrc" "$PATH_LINE"

# --- the pool: tasks, courses, catalog -- accounts made here stay on a re-install ----------------
say "кладу задания и курсы в $HOME_HP/registry"
REG="$HOME_HP/registry"
mkdir -p "$REG"
[ -d "$REG/store" ] && rm -rf "$REG/store.old" && mv "$REG/store" "$REG/store.old"
cp -a "$TMP/pool/store" "$REG/store"
cp "$TMP/pool/catalog.json" "$TMP/pool/config.json" "$REG/"
rm -rf "$REG/store.old"
LOGIN=""
if [ -f "$HOME_HP/pool.json" ] && grep -q '"local"' "$HOME_HP/pool.json"; then
  LOGIN="$(sed -n 's/.*"user": *"\([^"]*\)".*/\1/p' "$HOME_HP/pool.json" | head -1)"   # stay signed in
elif [ -f "$HOME_HP/pool.json" ]; then
  cp "$HOME_HP/pool.json" "$HOME_HP/pool.json.online"      # the online pool, kept for later
fi
printf '{"url": "http://127.0.0.1:%s", "user": "%s", "local": true}\n' "$PORT" "$LOGIN" > "$HOME_HP/pool.json"

# the first launch starts the pool by itself; start it now to see that it works
if "$BIN/hashpass" --no-update config pool >/dev/null 2>&1; then
  say "локальный пул: http://127.0.0.1:$PORT (веб — там же, в браузере)"
fi
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) say "В уже открытом терминале выполните:  source ~/.bashrc   (или откройте новый терминал)" ;;
esac
say "Готово. Запустите:  hashpass   (без sudo — пароль sudo он спросит сам)"
exit 0
