#!/bin/bash
# deploy.sh — собрать все Taskfile-задания и запушить в пул одной командой.
#
# Требования (только на машине автора, с настроенным scoped sudo для nspawn):
#   - hashengine установлен и активирован (`make install` в корне репо)
#   - hashengine login выполнен ХОТЯ БЫ РАЗ (Bearer-токен закэширован)
#   - в HASHPASS_POOL (или ~/.hashpass/pool.json) указан адрес пула
#
# Использование:
#   cd content/tasks && ./deploy.sh
#   ./deploy.sh --dry            # только собрать, не пушить
#
# Каждое задание собирается из своей папки; на пул уходит образ + Taskfile-attachment,
# и задание добавляется в каталог (--task).

set -euo pipefail
DRY=""
if [[ "${1:-}" == "--dry" ]]; then DRY="1"; fi

cd "$(dirname "$0")"
TASKS=(
    intro-hello        # 0 — знакомство, whoami
    simple-ls          # 1 — ls
    cat-file           # 2 — cat
    ls-la              # 3 — ls -la, скрытые файлы
    help-flag          # 4 — --help
    man-of-man         # 5 — man man
    cd-abs             # 6 — cd + pwd, абсолютные пути
    cp-basics          # 7 — cp одиночный
    cp-more            # 8 — cp -r, звёздочка
    mv-basics          # 9 — mv, rename
    rm-basics          # 10 — rm -rf, скрытые
    ls-mv-cp           # 11 — обход дерева с whitelist
    grep-search        # 12 — grep -r
    find-1             # 13 — find -maxdepth
    find-2             # 14 — find -mindepth+maxdepth+type
    find-3             # 15 — find -name
    find-4             # 16 — find -o (OR)
    find-5             # 17 — find -not -empty
    sudo-basics        # 18 — sudo touch/rm
    apt-update         # 19 — apt install sl
    apt-remove         # 20 — apt remove sl
    apt-add-repo       # 21 — добавить репозиторий
    apt-deb            # 22 — dpkg -i .deb
    star-wars          # 23 — приз: telnet
    vim-intro          # 24 — vim / vimtutor
    chmod-basics       # 25 — chmod NNN
    chgrp-basics       # 26 — chgrp
    chmod-evil         # 30 — chmod +/- относительная запись
    # старые (сохраняем на будущее)
    first-steps grep-hunt inventory fruit-store proc-audit showcase
)
USER_LOGIN="${HASHPASS_USER:-$(python3 -c 'import json,os;p=os.path.expanduser("~/.hashpass/pool.json");print(json.load(open(p)).get("user",""))' 2>/dev/null || true)}"
POOL_URL="${HASHPASS_POOL:-$(python3 -c 'import json,os;p=os.path.expanduser("~/.hashpass/pool.json");print(json.load(open(p)).get("url",""))' 2>/dev/null || true)}"

if [[ -z "$USER_LOGIN" ]]; then
    echo "нужен логин: HASHPASS_USER=... ./deploy.sh, либо предварительно  hashengine login" >&2
    exit 1
fi

# Пре-логин на пул: закэшируем bearer-токен один раз, чтобы дальнейшие 28 push-ей
# не спрашивали пароль на каждой итерации. Даже если токен уже свежий -- hashengine
# login просто перезапишет его и никого не побеспокоит (пароль спрашивается один раз).
if [[ -z "$DRY" ]]; then
    echo "── единоразовый вход на пул ($POOL_URL) от имени $USER_LOGIN ──"
    hashengine login "$POOL_URL" || {
        echo "вход на пул не удался — деплой прерван" >&2
        exit 1
    }
fi

for name in "${TASKS[@]}"; do
    echo
    echo "=== $name ==="
    (
        cd "$name"
        hashengine build Taskfile
        image_ref=$(grep -E '^image ' Taskfile | head -1 | awk '{print $2}')
        # image_ref = 'first-steps:1'; on the pool it lives under <login>/first-steps:1
        if [[ -z "$DRY" ]]; then
            hashengine push "$USER_LOGIN/$image_ref" --task 1
        fi
    )
done

echo
echo "готово. Проверьте пул: hashpass"
