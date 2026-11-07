#!/bin/sh
# Собрать ~/bot: пять коммитов, в третьем («Подключение к базе») вместе с config.sh в историю
# попал .env с паролем от базы. Даты и автор зафиксированы — хеши одни на любой машине.
# Запуск: mkrepo.sh <каталог-с-data> <репозиторий>
set -eu
src=$1 dst=$2
mkdir -p "$dst" && cd "$dst"
git init -q -b main
n=0
c() {
    n=$((n + 1))
    d="2026-11-0$n""T1$n:20:00+03:00"
    git add -A
    GIT_AUTHOR_NAME="Студент" GIT_AUTHOR_EMAIL="student@hashpass.local" GIT_AUTHOR_DATE="$d" \
    GIT_COMMITTER_NAME="Студент" GIT_COMMITTER_EMAIL="student@hashpass.local" GIT_COMMITTER_DATE="$d" \
        git commit -q -m "$1"
}
put() { cp "$src/bot/$1" "$1" && chmod "$2" "$1"; }
put README.md 644; c "README"
head -4 "$src/bot/bot.sh" > bot.sh
cat >> bot.sh <<'SH'
case "$q" in
    *оплат*)   echo "Оплата картой или наличными курьеру." ;;
    *)         echo "Не понял вопрос. Позвать оператора? Пишите: $SUPPORT_MAIL" ;;
esac
SH
chmod 755 bot.sh; c "Бот: ответы на частые вопросы"
put config.sh 644; put .env 600; c "Подключение к базе"
put bot.sh 755; c "Бот: ответ про доставку"
put README.md 644
printf '\nЗапуск: ./bot.sh "Сколько ждать доставку?"\n' >> README.md; c "README: как запускать"
