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
TASKS=(first-steps grep-hunt inventory fruit-store proc-audit showcase)
USER_LOGIN="${HASHPASS_USER:-$(python3 -c 'import json,os;p=os.path.expanduser("~/.hashpass/pool.json");print(json.load(open(p)).get("user",""))' 2>/dev/null || true)}"

if [[ -z "$USER_LOGIN" ]]; then
    echo "нужен логин: HASHPASS_USER=... ./deploy.sh, либо предварительно  hashengine login" >&2
    exit 1
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
