# journalctl

Службы systemd пишут не в файлы, а в общий **журнал** systemd. Читают его так:

    journalctl -u cron              записи одной службы
    journalctl -b                   всё с последней загрузки
    journalctl -u cron -o cat       только сообщения — без даты, машины и имени

Записи служб видит администратор — через `sudo`.
