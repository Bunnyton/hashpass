image:
```
bunnyton/apt:add_repo
```

readme.txt
```


Мы уже говорили о том, что можно добавлять репозитории. Для этого нужно добавить ключ и внести соответствующую запись в конфигурационный файл, давай сделаем это!

#Задание
Добавь один из самых популярных репозиториев

sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
```
/.hash/dvs/hooks/all.py
```python
@check(stages=None)
def check_apt_update(cmd: str, stage:int):
    if Cmd(cmd) != Cmd("sudo apt update"):
        return False
```

