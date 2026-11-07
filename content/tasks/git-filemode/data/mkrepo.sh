#!/bin/sh
# Собрать репозиторий конфигов ~/ops (50 файлов: конфиги 644, скрипты 755), затем «вернуть его с
# флешки»: FAT не хранит права, и все файлы стали 755. Настоящая правка одна — в
# logrotate/app.conf журналы хранятся 14 дней вместо 7. Даты и автор зафиксированы — вершина
# одинакова на любой машине (её сверяет hp/state).
# Запуск: mkrepo.sh <куда>
set -eu
dst=$1
mkdir -p "$dst"
cd "$dst"
git init -q -b main
n=0
c() {
    n=$((n + 1))
    d="2026-09-0${n}T12:00:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="Игорь Петров" GIT_AUTHOR_EMAIL="igor@pelmen.local" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="Игорь Петров" GIT_COMMITTER_EMAIL="igor@pelmen.local" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$1"
}
mkdir -p nginx/sites logrotate cron scripts env
for s in shop api admin blog menu courier delivery static images cdn pay auth; do
    cat > "nginx/sites/$s.conf" <<CONF
server {
    listen 80;
    server_name $s.pelmen.local;
    root /srv/www/$s;
    access_log /var/log/nginx/$s.access.log;
    error_log  /var/log/nginx/$s.error.log;
}
CONF
done
printf 'user www-data;\nworker_processes auto;\ninclude /etc/nginx/sites/*.conf;\n' > nginx/nginx.conf
for s in app nginx postgres redis courier pay; do
    cat > "logrotate/$s.conf" <<CONF
/var/log/$s/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
CONF
done
for j in backup-db backup-site clean-tmp report-daily report-weekly sync-menu sync-prices \
         renew-certs check-disk check-queue warm-cache vacuum-db; do
    printf '# %s\n0 %d * * * ops /opt/ops/scripts/%s.sh\n' "$j" $(( ${#j} % 24 )) "$j" > "cron/$j.txt"
done
for j in backup-db backup-site clean-tmp report-daily report-weekly sync-menu sync-prices \
         renew-certs check-disk check-queue warm-cache vacuum-db deploy rollback; do
    printf '#!/bin/sh\n# %s — задача обслуживания\nset -eu\necho "%s: готово"\n' "$j" "$j" > "scripts/$j.sh"
    chmod 755 "scripts/$j.sh"
done
for e in prod stage dev test; do
    printf 'APP_ENV=%s\nLOG_LEVEL=info\nDB_HOST=db.%s.pelmen.local\n' "$e" "$e" > "env/$e.env"
done
printf '# Конфиги серверов «Пельменя»\n\nnginx/, logrotate/, cron/, scripts/, env/\n' > README.md
find . -path ./.git -prune -o -type f ! -name '*.sh' -exec chmod 644 {} +
c "Конфиги серверов"
sed -i 's/LOG_LEVEL=info/LOG_LEVEL=warn/' env/prod.env; c "prod: меньше логов"
sed -i 's/worker_processes auto;/worker_processes 4;/' nginx/nginx.conf; c "nginx: 4 воркера"
# «с флешки»: права потеряны, и одна настоящая правка
find . -path ./.git -prune -o -type f -exec chmod 755 {} +
sed -i 's/rotate 7/rotate 14/' logrotate/app.conf
