# changelog

Версию пакета `dpkg-buildpackage` берёт не из `control`, а из `debian/changelog` — у него
строгий формат, поэтому его не пишут руками. Создаёт его `dch` (из `devscripts`):

```sh
dch --create --package hello-cat -v 0.3 "Первый выпуск."
```

Кто ты, `dch` узнаёт из переменных `DEBFULLNAME` и `DEBEMAIL`.
