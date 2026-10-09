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
#   ./deploy.sh --layout         # только раскладка каталога по BLOCKS (без сборки и push)
#
# Каждое задание собирается из своей папки; на пул уходит образ + Taskfile-attachment,
# и задание добавляется в каталог (--task).

set -euo pipefail
DRY=""
FORCE=""
LAYOUT_ONLY=""
for a in "$@"; do
    case "$a" in
        --dry)    DRY="1" ;;
        --force)  FORCE="--force" ;;
        --layout) LAYOUT_ONLY="1" ;;
    esac
done

cd "$(dirname "$0")"
# Блоки каталога по темам. Порядок блоков и заданий внутри = нумерация на пуле: после всех
# push-ей раскладка целиком отправляется `hashengine catalog layout` (только администратор).
# Формат строки: 'Название блока: каталог каталог …' (имена каталогов заданий здесь).
BLOCKS=(
    'Знакомство: intro-hello simple-ls cat-file ls-la help-man cd-abs'
    'Файлы и каталоги: cp-basics cp-more mv-basics rm-basics ls-mv-cp inventory'
    'Поиск: grep-search pipes grep-hunt find-1 find-2 find-3 find-4 find-5'
    'Права и пользователи: sudo-basics chmod-basics chgrp-basics chmod-evil'
    'Пакеты и процессы: apt-update apt-remove apt-add-repo apt-deb proc-audit'
    'Редактор и текст: vim-intro fruit-store'
    'Призы: star-wars'
    'Архив: first-steps showcase'
)
# Порядок сборки/пуша — тот же, что в блоках (родитель из `from` раньше потомка).
TASKS=()
for block in "${BLOCKS[@]}"; do
    read -r -a names <<< "${block#*:}"
    TASKS+=("${names[@]}")
done
# Must equal the namespace the images were built under -- `hashengine build` namespaces images
# by the LOCAL login, and the pool now rejects a push whose ref namespace differs from the
# pushing user (author == author): a mismatch here gets a 403, not a silent wrong owner.
USER_LOGIN="${HASHPASS_USER:-$(python3 -c 'import json,os;p=os.path.expanduser("~/.hashpass/pool.json");print(json.load(open(p)).get("user",""))' 2>/dev/null || true)}"
POOL_URL="${HASHPASS_POOL:-$(python3 -c 'import json,os;p=os.path.expanduser("~/.hashpass/pool.json");print(json.load(open(p)).get("url",""))' 2>/dev/null || true)}"

if [[ -z "$USER_LOGIN" ]]; then
    echo "нужен логин: HASHPASS_USER=... ./deploy.sh, либо предварительно  hashengine login" >&2
    exit 1
fi

# Пре-логин на пул: закэшируем bearer-токен один раз, чтобы дальнейшие 28 push-ей
# не спрашивали пароль на каждой итерации. --if-needed: если токен уже свежий, login
# только подтверждает это и не задаёт вопрос "перезайти?" -- деплой не должен
# блокироваться на вводе.
if [[ -z "$DRY" ]]; then
    echo "── единоразовый вход на пул ($POOL_URL) от имени $USER_LOGIN ──"
    hashengine login "$POOL_URL" --if-needed || {
        echo "вход на пул не удался — деплой прерван" >&2
        exit 1
    }
fi

if [[ -z "$DRY" && -z "$LAYOUT_ONLY" ]]; then
    echo "── базовый образ (bunnyton/debian:trixie) ──"
    # БЕЗ $FORCE: тег фиксированный, `push base` сам сравнивает digest ЭТОГО пула с тем,
    # что эта машина на него заливала: уходит база, пересобранная здесь (новый runtime) или
    # с машины, которая на этот пул базу ещё не заливала; неизменная не отправляется, а
    # залитую с другой машины он не трогает (скажет об этом). --force перезалил бы базу и
    # заставил КАЖДОГО студента заново скачать ~57 МБ; если это действительно нужно — вручную:
    #   hashengine push base --force
    # Логин на пул должен быть владельцем базы (bunnyton) или администратором.
    hashengine push base
fi

declare -A REF_OF
for name in "${TASKS[@]}"; do
    # image_ref = 'first-steps:1'; on the pool it lives under <login>/first-steps:1
    image_ref=$(grep -E '^image ' "$name/Taskfile" | head -1 | awk '{print $2}')
    REF_OF[$name]="$USER_LOGIN/$image_ref"
    [[ -n "$LAYOUT_ONLY" ]] && continue
    echo
    echo "=== $name ==="
    (
        cd "$name"
        hashengine build Taskfile
        if [[ -z "$DRY" ]]; then
            hashengine push "$USER_LOGIN/$image_ref" --task $FORCE
        fi
    )
done

# Раскладка каталога: блоки по темам, нумерация по порядку; задания, которых больше нет в
# BLOCKS (например, старые help-flag / man-of-man), из каталога уходят (образы остаются).
SPECS=()
for block in "${BLOCKS[@]}"; do
    title="${block%%:*}"
    read -r -a names <<< "${block#*:}"
    refs=()
    for n in "${names[@]}"; do refs+=("${REF_OF[$n]}"); done
    SPECS+=("$title: ${refs[*]}")
done
if [[ -z "$DRY" ]]; then
    echo
    echo "── раскладка каталога по блокам ──"
    hashengine catalog layout --registry "$POOL_URL" "${SPECS[@]}"
fi

echo
echo "готово. Проверьте пул: hashpass"
