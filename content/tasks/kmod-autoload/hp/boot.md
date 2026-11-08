# Автозагрузка

При старте системы `systemd-modules-load` читает `/etc/modules-load.d/*.conf` — в каждом по
имени модуля на строку — и загружает их `modprobe`:

```
# /etc/modules-load.d/vhost.conf
vhost_net
```

Учебное ядро делает при старте то же самое. Перезагрузить его — `sudo systemctl restart hpkernel`
(консоль и файлы останутся).
