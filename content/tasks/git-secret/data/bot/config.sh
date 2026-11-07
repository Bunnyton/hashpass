# Настройки бота: секреты — из .env рядом (в git его быть не должно).
[ -f .env ] && . ./.env
SUPPORT_MAIL=${SUPPORT_MAIL:-help@pelmen.local}
DB_URL="postgres://$DB_USER:$DB_PASSWORD@$DB_HOST/support"
