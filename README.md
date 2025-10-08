![hashpass](/photo/hashpass.png)

Данный проект призван облегчить освоение пользователями Linux. При помощи данного проекта легко можно создавать и выполнять интерактивные задания под Linux.

Базовые учетные данные для всех заданий:
```
student:student
```

#### Установка
В терминале (ctrl + alt + T):
```
sudo apt update
```
```
sudo apt install -y curl
```

Для Amd64
```
curl https://gitlab.com/Bunnyton/hashpass/-/raw/main/install/install.sh?ref_type=heads | bash
```

Для Arm64 (не работает)
```
curl https://gitlab.com/Bunnyton/hashpass/-/raw/main/install/install_arm.sh?ref_type=heads | bash
```
```
sudo hashpass
```

#### запуск
Для того, чтобы приступить к решению задач выполните:
```
sudo hashpass
```

Может выскочить:
```
The authenticity of host 'gitlab.com (172.65.251.78)' can't be established.
ED25519 key fingerprint is SHA256:eUXGGm1YGsMAS7vkcx6JOJdOGHPem5gQp4taiCfCLB8.
This key is not known by any other names.
Are you sure you want to continue connecting (yes/no/[fingerprint])? yes
```
Введите yes, больше данная надпись выскакивать не будет
