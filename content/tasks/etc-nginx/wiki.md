---
tags: etc, конфиги, nginx, systemctl, службы
---
# Конфиг и служба

Почти у каждой программы в Linux настройки — текстовый файл. Системные — в `/etc`, обычно в
каталоге с именем программы: `/etc/ssh/sshd_config`, `/etc/nginx/`, `/etc/postgresql/`. Править их
может только root, поэтому редактор запускают через `sudo` (`sudo vim файл`).

## Как найти нужную настройку

Файлов бывает много. Ищут по содержимому — `grep -r` по всему каталогу:

    $ grep -r 8472 /etc/nginx
    /etc/nginx/sites-available/default:	listen 127.0.0.1:8472;

Строки с `#` в начале — комментарии, программа их пропускает. Часто в конфиге уже есть нужная
строка, закомментированная, с значением по умолчанию — её раскомментируют и меняют.

## Как устроен /etc/nginx

    $ ls /etc/nginx
    conf.d	      fastcgi_params  koi-win	  modules-available  nginx.conf    scgi_params	    sites-enabled  uwsgi_params
    fastcgi.conf  koi-utf	      mime.types  modules-enabled    proxy_params  sites-available  snippets	   win-utf
    $ ls -l /etc/nginx/sites-enabled
    lrwxrwxrwx 1 root root 34 Nov  4 02:46 default -> /etc/nginx/sites-available/default

`nginx.conf` — главный файл, он подключает всё из `sites-enabled/`. Сами сайты лежат в
`sites-available/`, а включают их ссылкой в `sites-enabled/`: выключить сайт — удалить ссылку,
файл останется. Тот же приём у Apache и у модулей.

В nginx каждая настройка заканчивается `;`, а блоки — фигурными скобками:

    server {
        listen 127.0.0.1:8472;
        root /var/www/snab;
    }

## Программа читает конфиг при запуске

Самое важное в этой теме: поправить файл — мало. Работающая программа прочитала настройки при
старте и держит их в памяти. Чтобы она увидела правку, её просят перечитать конфиг:

    sudo systemctl reload nginx     перечитать, не обрывая соединения (если служба умеет)
    sudo systemctl restart nginx    остановить и запустить заново

`reload` умеют не все службы; `systemctl reload` скажет, если нет.

## Проверяй, прежде чем перезапускать

Сломанный конфиг + `restart` = служба не поднимется, и сайт ляжет целиком:

    $ sudo systemctl restart nginx
    Job for nginx.service failed because the control process exited with error code.
    See "systemctl status nginx.service" and "journalctl -xeu nginx.service" for details.

Что случилось — в журнале службы или в проверке конфига. У nginx она встроенная:

    $ sudo nginx -t
    2026/11/04 03:09:39 [emerg] 382#382: unexpected "}" in /etc/nginx/sites-enabled/default:14
    nginx: configuration file /etc/nginx/nginx.conf test failed

Ошибка, файл и номер строки. Здесь «неожиданная `}`» на строке 14 значит, что на строке выше
не хватает `;`. После исправления:

    $ sudo nginx -t
    nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
    nginx: configuration file /etc/nginx/nginx.conf test is successful

Проверка есть у многих: `sshd -t`, `apachectl configtest`, `visudo -c`, `named-checkconf`. Привычка
«сначала проверь, потом перезапусти» спасает от падений.

## Источники

- [nginx: руководство для начинающих](https://nginx.org/ru/docs/beginners_guide.html) — как устроен конфиг, перезагрузка конфигурации.
- [nginx: модуль ngx_http_core_module](https://nginx.org/ru/docs/http/ngx_http_core_module.html) — `listen`, `location`, `root`.
- [nginx: ключи командной строки](https://nginx.org/en/docs/switches.html) — `-t`, `-s reload`.
- [systemd/Journal — Arch Wiki](https://wiki.archlinux.org/title/Systemd/Journal) — журнал служб, когда служба не стартует.
