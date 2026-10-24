#!/usr/bin/env bash
# Build the offline installer: ONE file that installs hashpass on a machine with no network at all
# (user 2026-10-24: «сделай оффлайн установщик, полный, абсолютно автономный»).
#
#   scripts/offline/build.sh [--pool-data DIR] [-o OUT]
#
# The file carries everything the online install and a run download:
#   python/   a standalone CPython 3.13 (python-build-standalone) -- the target's own Python is moot;
#   wheels/   hashpass (this checkout's HEAD) + flask, textual and their dependencies;
#   sys/      systemd-nspawn, machinectl, systemd-machined and rsync with every library they load,
#             glibc included -- for a Debian/Ubuntu/Fedora without systemd-container (or rsync);
#   pool/     a copy of the pool's tasks, courses and catalog, WITHOUT accounts or progress
#             (sanitize.py) -- the student's hashpass serves it on 127.0.0.1.
# Build on Debian 13 (x86_64) with systemd-container and rsync installed: sys/ is taken from here.
# The pool data comes from --pool-data (a pool's registry dir), else read over ssh from the prod
# pool (rsync, read-only).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/dist/hashpass-offline-x86_64.run"
POOL_DATA=""
PROD="root@135.106.177.228:/root/.hashpass/registry/"
WORK="${HP_OFFLINE_WORK:-/var/tmp/hp-offline}"
PY_RELEASE="20261009"                 # python-build-standalone release (pinned, >2 weeks old)
PY_VERSION="3.13.16"
PY_ASSET="cpython-${PY_VERSION}+${PY_RELEASE}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
PY_SHA256="24801ea31c7d406d559a17e2226325c723d50c56900b9c0da7b62adaae2affc9"   # its SHA256SUMS
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_RELEASE}/${PY_ASSET/+/%2B}"

while [ $# -gt 0 ]; do
  case "$1" in
    --pool-data) POOL_DATA="$2"; shift 2 ;;
    -o) OUT="$2"; shift 2 ;;
    *) echo "неизвестный аргумент: $1" >&2; exit 2 ;;
  esac
done

say() { printf '\033[36m== %s\033[0m\n' "$*"; }
[ "$(uname -m)" = x86_64 ] || { echo "собирать нужно на x86_64" >&2; exit 1; }
for b in systemd-nspawn machinectl rsync; do
  command -v "$b" >/dev/null || { echo "нет $b на машине сборки (systemd-container, rsync)" >&2; exit 1; }
done

export PIP_DISABLE_PIP_VERSION_CHECK=1
STAGE="$WORK/stage"
rm -rf "$STAGE"
mkdir -p "$STAGE"/{wheels,sys/bin,sys/lib,sys/libexec} "$WORK/cache" "$(dirname "$OUT")"

say "Python $PY_VERSION"
[ -s "$WORK/cache/$PY_ASSET" ] || curl -fsSL --retry 3 -o "$WORK/cache/$PY_ASSET" "$PY_URL"
echo "$PY_SHA256  $WORK/cache/$PY_ASSET" | sha256sum -c --quiet - || { echo "Python: не та сумма" >&2; exit 1; }
cp "$WORK/cache/$PY_ASSET" "$STAGE/python.tar.gz"
PYDIR="$WORK/python"
rm -rf "$PYDIR" && mkdir -p "$PYDIR" && tar -xzf "$STAGE/python.tar.gz" -C "$PYDIR"
PY="$PYDIR/python/bin/python3"

REV="$(git -C "$ROOT" stash create)"   # the tracked files as they are now (HEAD when clean)
REV="${REV:-$(git -C "$ROOT" rev-parse HEAD)}"
say "hashpass ${REV:0:7} + зависимости"
SRC="$WORK/src"
rm -rf "$SRC" && mkdir -p "$SRC"
git -C "$ROOT" archive "$REV" | tar -x -C "$SRC"          # never untracked files
"$PY" -m pip wheel --quiet --no-deps -w "$STAGE/wheels" "$SRC"
"$PY" -m pip download --quiet --only-binary=:all: -d "$STAGE/wheels" "$STAGE"/wheels/hashpass-*.whl

say "systemd-nspawn, machinectl, systemd-machined, rsync (с библиотеками)"
take() {   # take NAME PATH -- the program, its libraries, and a wrapper that runs it on our glibc
  cp -L "$2" "$STAGE/sys/libexec/$1"
  ldd "$2" | awk '/=> \//{print $3} /^\t\/.*ld-linux/{print $1}' | while read -r lib; do
    cp -Ln "$lib" "$STAGE/sys/lib/" 2>/dev/null || true
  done
  cat > "$STAGE/sys/bin/$1" <<EOF
#!/bin/sh
exec /opt/hashpass-sys/lib/ld-linux-x86-64.so.2 --library-path /opt/hashpass-sys/lib /opt/hashpass-sys/libexec/$1 "\$@"
EOF
  chmod 755 "$STAGE/sys/bin/$1"
}
take systemd-nspawn "$(command -v systemd-nspawn)"
take machinectl "$(command -v machinectl)"
take systemd-machined /usr/lib/systemd/systemd-machined
take rsync "$(command -v rsync)"
cp -L /usr/share/dbus-1/system.d/org.freedesktop.machine1.conf "$STAGE/sys/"
cat > "$STAGE/sys/systemd-machined.service" <<'EOF'
# hashpass offline install: machined for systemd-nspawn consoles (this system had no systemd-container)
[Unit]
Description=Virtual Machine and Container Registration Service (hashpass)
Wants=machine.slice
After=machine.slice

[Service]
BusName=org.freedesktop.machine1
ExecStart=/opt/hashpass-sys/bin/systemd-machined

[Install]
WantedBy=multi-user.target
Alias=dbus-org.freedesktop.machine1.service
EOF

say "задания, курсы и каталог пула (без аккаунтов)"
if [ -z "$POOL_DATA" ]; then
  POOL_DATA="$WORK/snap"
  mkdir -p "$POOL_DATA"
  rsync -a -H --delete -e "ssh -o BatchMode=yes" \
    --exclude users.json --exclude progress --exclude attempts --exclude secret --exclude tls \
    "$PROD" "$POOL_DATA/"
fi
python3 "$ROOT/scripts/offline/sanitize.py" "$POOL_DATA" "$STAGE/pool"

printf 'commit %s\nbuilt %s\npython %s\n' "$REV" "$(date -u +%FT%TZ)" \
  "$PY_VERSION" > "$STAGE/VERSION"

say "сборка $OUT"
cat "$ROOT/scripts/offline/installer.sh" > "$OUT.tmp"
printf '\n__PAYLOAD_BELOW__\n' >> "$OUT.tmp"
tar -C "$STAGE" -cf - . >> "$OUT.tmp"
chmod 755 "$OUT.tmp"
mv "$OUT.tmp" "$OUT"
( cd "$(dirname "$OUT")" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )
ls -lh "$OUT"
