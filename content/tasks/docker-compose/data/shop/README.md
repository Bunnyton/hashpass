# Магазин в контейнерах

Как запускаем сейчас (каждый раз руками, в таком порядке):

    docker network create shop
    docker run -d --name stock --network shop stock
    docker run -d --name shopfront --network shop -p 8080:80 shopfront

Витрина ищет склад по адресу http://stock/.
Свежие остатки склада — в stock/stock.txt (склад отдаёт файлы из своего каталога /www).
