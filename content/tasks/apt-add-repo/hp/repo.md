# Репозиторий Docker

apt не нашёл пакет: в репозиториях Debian его нет — он живёт в репозитории самого Docker.
Как подключить свой репозиторий, производитель пишет сам. Вот инструкция Docker для Debian:

    sudo apt update
    sudo apt install ca-certificates curl
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc

    # Add the repository to Apt sources:
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt update

`$( … )` подставляет вывод команды прямо в строку — здесь это архитектура и кодовое имя
версии Debian.
