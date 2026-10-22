# Репозиторий Docker

apt не нашёл пакет: в репозиториях Debian его нет — он живёт в репозитории самого Docker.
Как его подключить, производитель пишет сам. Вот инструкция Docker для Debian — по шагам.

**1. Инструменты.** `curl` скачает ключ, `ca-certificates` — чтобы доверять сайту по https:

    sudo apt update
    sudo apt install ca-certificates curl

**2. Ключ.** Каталог для ключей (`install -d` — это `mkdir`, сразу с правами), сам ключ с сайта
Docker (`-o` — куда сохранить) и право читать его всем — apt должен его открыть:

    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc

**3. Запись.** Одна строка в новый файл `/etc/apt/sources.list.d/docker.list`:

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

Это одна команда: `\` в конце строки значит «продолжение на следующей». Что в записи:

- `deb` — репозиторий готовых пакетов;
- `arch=…` — архитектура процессора; `$( … )` подставляет вывод команды прямо в строку,
  здесь получится `amd64`;
- `signed-by=…` — каким ключом проверять подписи: тем, что скачали на шаге 2;
- адрес сервера, затем версия Debian — `$( … )` достанет её имя из `/etc/os-release`
  (`trixie`) — и раздел `stable`.

Почему `| sudo tee`, а не `sudo echo … > файл`: перенаправление `>` делает твоя оболочка, а у
неё нет прав писать в `/etc` — `sudo` действует только на `echo`. `tee` записывает в файл то,
что пришло по конвейеру, и запущен он уже через `sudo`. Заодно tee печатает то же на экран —
эту копию прячет `> /dev/null`.

**4. Обновить список.** apt прочитает новую запись и скачает список пакетов Docker:

    sudo apt update

После этого пакеты Docker ставятся обычным `apt install`. Копировать команды из теории
удобно так: зажми **Shift** и выдели мышью.
