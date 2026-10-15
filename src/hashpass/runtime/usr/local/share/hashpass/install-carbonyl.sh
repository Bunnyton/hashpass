#!/bin/sh
# install-carbonyl.sh -- Chromium прямо в терминале (https://github.com/fathyb/carbonyl).
#
#   sudo sh install-carbonyl.sh [carbonyl.linux-<arch>.zip]
#
# Кладёт браузер в /opt/carbonyl и команду /usr/local/bin/carbonyl (Debian/Ubuntu, amd64/arm64).
# Архив можно передать готовым (так собирается база hashpass), иначе он скачивается с GitHub
# (curl, wget или python3 -- что найдётся). В контейнере hashpass звука нет -- только картинка.
#   carbonyl https://example.com        -- открыть страницу; выход -- Ctrl+C
set -eu

VERSION=0.0.3
SHA256_amd64=46a902ea29bb32f773fb4ee341423705b92345a810422b8df93eaea6a1ec7ad2
SHA256_arm64=""                       # не закреплена: архив arm64 не сверяется

if [ "$(id -u)" != 0 ]; then
    echo "install-carbonyl.sh: нужен root -- запусти через sudo" >&2
    exit 1
fi

arch=$(dpkg --print-architecture)
case "$arch" in
    amd64) want=$SHA256_amd64 ;;
    arm64) want=$SHA256_arm64 ;;
    *) echo "install-carbonyl.sh: carbonyl собран только для amd64 и arm64, а здесь $arch" >&2; exit 1 ;;
esac

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# Что нужно самому Chromium; libasound2 в Debian 13 называется libasound2t64.
apt-get install -y -qq --no-install-recommends unzip ca-certificates libnss3 libexpat1 \
    libfontconfig1 fonts-dejavu-core >/dev/null
apt-get install -y -qq --no-install-recommends libasound2t64 >/dev/null 2>&1 \
    || apt-get install -y -qq --no-install-recommends libasound2 >/dev/null

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
zip=${1:-}
if [ -z "$zip" ]; then
    url="https://github.com/fathyb/carbonyl/releases/download/v$VERSION/carbonyl.linux-$arch.zip"
    zip="$tmp/carbonyl.zip"
    echo "скачиваю $url"
    if command -v curl >/dev/null; then curl -fL --retry 5 -C - -o "$zip" "$url"
    elif command -v wget >/dev/null; then wget -c -O "$zip" "$url"
    else python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$url" "$zip"
    fi
fi
if [ -n "$want" ]; then
    got=$(sha256sum "$zip" | cut -d' ' -f1)
    if [ "$got" != "$want" ]; then
        echo "install-carbonyl.sh: архив не тот (sha256 $got, ждали $want)" >&2
        exit 1
    fi
fi

unzip -q "$zip" -d "$tmp/x"
bin=$(find "$tmp/x" -type f -name carbonyl | head -n 1)
[ -n "$bin" ] || { echo "install-carbonyl.sh: в архиве нет carbonyl" >&2; exit 1; }
rm -rf /opt/carbonyl
mv "$(dirname "$bin")" /opt/carbonyl
chmod -R a+rX /opt/carbonyl

# --no-sandbox: песочнице Chromium нужны user namespaces, которых в контейнере нет.
cat > /usr/local/bin/carbonyl <<'SH'
#!/bin/sh
exec /opt/carbonyl/carbonyl --no-sandbox "$@"
SH
chmod 755 /usr/local/bin/carbonyl
echo "carbonyl $VERSION установлен: carbonyl <адрес>"
