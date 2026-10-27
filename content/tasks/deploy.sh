#!/bin/bash
# deploy.sh — собрать задания, отправить их на пул и разложить по курсам.
#
# Две отдельные операции, как и в вебе (пользователь, 2026-10-27: «унификация»):
#   1. hashpass push <образ>                                  — новая версия образа на пуле;
#   2. hashpass course <курс> add block <блок>                 — блок в курсе (если его нет),
#      hashpass course <курс> block <блок> add <ref>…          — задания в блок.
# Обе ходят в один API пула — тот же, что страница курса в браузере.
#
# Требования: hashpass login выполнен (токен закэширован), адрес пула — в HASHPASS_POOL
# или ~/.hashpass/pool.json. Сборка идёт в nspawn (scoped sudo).
#
# Использование:
#   cd content/tasks && ./deploy.sh            # собрать, отправить, разложить по курсам
#   ./deploy.sh --dry                          # только собрать
#   ./deploy.sh --layout                       # только разложить по курсам (без сборки и push)
#   ./deploy.sh --force                        # отправить даже без изменений
# Любой другой аргумент — ошибка: скрипт ничего не делает (2026-10-26 `--help` молча запустил
# настоящий деплой).

set -euo pipefail
DRY=""
FORCE=""
LAYOUT_ONLY=""
usage() { sed -n '2,19p' "$0"; }
for a in "$@"; do
    case "$a" in
        --dry)    DRY="1" ;;
        --force)  FORCE="--force" ;;
        --layout) LAYOUT_ONLY="1" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "deploy.sh: неизвестный аргумент «$a» — ничего не делаю" >&2; usage >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")"
# курс | блок: задания — в порядке курса; родитель задания (from) стоит раньше потомка
BLOCKS=(
    'bunnyton/linux | Знакомство: intro-hello first-commands cd-abs'
    'bunnyton/linux | Файлы и каталоги: cp-basics cp-more mv-basics rm-basics inventory ls-mv-cp links mc'
    'bunnyton/linux | Поиск: pipes streams grep-hunt find xargs'
    'bunnyton/linux | Права и пользователи: sudo-basics chmod-basics chgrp-basics chmod-evil'
    'bunnyton/linux | Пакеты и процессы: apt-update apt-remove apt-add-repo apt-deb proc-audit top'
    'bunnyton/linux | Редактор и текст: vim-intro vim-more fruit-store'
    'bunnyton/linux | Скрипты: my-command'
    'bunnyton/git-docker | Git: git-init git-log git-branch git-remote'
    'bunnyton/git-docker | Git — глубже: git-ignore git-reset git-conflict git-stash git-rebase git-squash git-cherry-pick'
    'bunnyton/git-docker | Git — мастер: git-reflog git-bisect git-internals git-hooks git-deploy'
    'bunnyton/docker | Docker: docker-run docker-web docker-ports docker-volume docker-db docker-build docker-layers'
    'bunnyton/docker | Docker — глубже: docker-debug docker-network docker-compose docker-multistage docker-registry'
    'bunnyton/docker | Docker — под капотом: docker-inside docker-limits docker-caps'
    'bunnyton/docker | Docker Compose: compose-health compose-config compose-scale'
    'bunnyton/linux | Призы: star-wars moria'
    'bunnyton/linux | Архив: first-steps showcase'
)
TASKS=()
declare -A BLOCK_OF COURSE_OF
for line in "${BLOCKS[@]}"; do
    c="${line%% | *}"; block="${line#* | }"
    read -r -a names <<< "${block#*:}"
    TASKS+=("${names[@]}")
    for n in "${names[@]}"; do BLOCK_OF[$n]="${block%%:*}"; COURSE_OF[$n]="$c"; done
done
USER_LOGIN="${HASHPASS_USER:-$(python3 -c 'import json,os;p=os.path.expanduser("~/.hashpass/pool.json");print(json.load(open(p)).get("user",""))' 2>/dev/null || true)}"
if [[ -z "$USER_LOGIN" ]]; then
    echo "нужен логин: hashpass login" >&2
    exit 1
fi

if [[ -z "$DRY" && -z "$LAYOUT_ONLY" ]]; then
    echo "── базовый образ (bunnyton/debian:trixie) ──"
    hashpass push base
fi

declare -A REF_OF
for name in "${TASKS[@]}"; do
    image_ref=$(grep -E '^image ' "$name/Taskfile" | head -1 | awk '{print $2}')
    REF_OF[$name]="$USER_LOGIN/$image_ref"
    [[ -n "$LAYOUT_ONLY" ]] && continue
    echo
    echo "=== $name ==="
    (
        cd "$name"
        hashpass build Taskfile
        if [[ -z "$DRY" ]]; then
            hashpass push "$USER_LOGIN/$image_ref" --public $FORCE
        fi
    )
done

[[ -n "$DRY" ]] && { echo; echo "собрано, на пул ничего не отправлено"; exit 0; }
echo
echo "── раскладка по курсам ──"
for line in "${BLOCKS[@]}"; do
    c="${line%% | *}"; block="${line#* | }"; title="${block%%:*}"
    read -r -a names <<< "${block#*:}"
    refs=()
    for n in "${names[@]}"; do refs+=("${REF_OF[$n]}"); done
    hashpass course "$c" add block "$title"
    hashpass course "$c" block "$title" add "${refs[@]}"
done
echo
echo "готово. Курсы: hashpass course"
