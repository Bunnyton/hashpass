# Лавка «У дома»: прайс-лист в контейнере
FROM busybox

# Всё приложение — в образ
COPY . /app

# Поставить библиотеки из deps.txt
RUN sh /app/install-deps.sh

# Показать прайс
CMD ["sh", "/app/app.sh"]
