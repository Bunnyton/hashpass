image:
```
bunnyton/sudo:intro
```

readme.txt
```
Настало время познакомиться с тем, как же запускается hashpass:
sudo hashpass

Дело в том, что в Linux существуют пользователи, можно создать их несколько, переключаться между ними

Пользователи ограничены в правах и действиях, например, они не могут поменять владельца файла (об этом позже), не могут вызвать системные команды

Но есть один пользователь, которого именуют root
Этот пользователь всегда существует, его еще называет суперпользователь

Так вот, у него эти ограничения сведены к минимуму, он может натворить проблем, если пользоваться его возможностями неумело

Но чтобы все время не заходить под новым пользователем, придумали sudo - superuser do

Она выполняет команду от имени суперпользователя
При этом, пароль запрашивается от текущего пользователя, если он имеет права на выполнение sudo, то команда будет выполнена от имени суперпользователя

#Задание 
Создайте файл /home/file.txt и посмотрите полную информацию о нем
```

stage 0:
```
sudo touch /home/file.txt
```

```
ls -l /home/file.txt
```
stage 0:
```
action echo -e "\nОбрати внимание, создателем файла указан root, а в директории /home чтобы создать файл обычных прав не хватает))"
```
```
action echo -e "\nА теперь удали его"
```

stage 1:
```
rm /home/file.txt
```
stage 1:
```
action echo -e "\nА теперь используй sudo"
```
stage 2:
```
sudo rm /home/file.txt
```
stage 2:

```
action echo -e "\nНо можно натворить бед, неправильно используя свои права, но если в обычной системе - больно, то здесь - можно попробовать"
```

```
action echo -e "\nПопробуй sudo rm -rf /     ;)"
```
stage 3:
```
sudo rm -rf /
```
stage 3:
/opt/fatality.txt
```
 _______  _______ _________ _______  _       __________________
(  ____ \(  ___  )\__   __/(  ___  )( \      \__   __/\__   __/|\     /|
| (    \/| (   ) |   ) (   | (   ) || (         ) (      ) (   ( \   / )
| (__    | (___) |   | |   | (___) || |         | |      | |    \ (_) / 
|  __)   |  ___  |   | |   |  ___  || |         | |      | |     \   /
| (      | (   ) |   | |   | (   ) || |         | |      | |      ) (
| )      | )   ( |   | |   | )   ( || (____/\___) (___   | |      | |
|/       |/     \|   )_(   |/     \|(_______/\_______/   )_(      \_/
```
/.hash/dvs/hooks/all.py
```python
from hooks.engine import *
from cmd import Cmd, parse_cmds

import os
import re
import argparse
import shlex


@command(stages=None)
def rm_rf(cmd: str, stage: int):
    res = {"before": []
        , "cmd": [cmd]
        , "after": []}

    cmds = parse_cmds(cmd)

    if len(cmds) == 1:
        if not os.path.exists("/opt/fatality.txt"):
            res = {"before": [' '.join(['echo \"bash:', cmds[0].basecmd, ': command not found\"'])]
                    , "cmd": []
                    , "after": []}

        elif Cmd("sudo rm -rf /") == cmds[0]:
            res = {"before": ["cat /opt/fatality.txt"]
                , "cmd": ['echo -e "\nДаже эта система будет плохо чувствовать после такого..."']
                , "after": ["rm /opt/fatality.txt"]}

        elif Cmd("sudo rm -r") in cmds[0]:
            res = {"before": ["echo 'Не рекомендую шутить с этой командой))'"]
                    , "cmd": []
                    , "after": []}

    return res

@command(stages=[1])
def rm_rf(cmd: str, stage: int):
    res = {"before": []
            , "cmd": [cmd]
            , "after": []}

    cmds = parse_cmds(cmd)

    if cmds[0].is_sudo:
        res = {"before": ["echo -e \"\nСначала без sudo\" "]
                , "cmd": []
                , "after": []}

    return res

@filter(stages=None)
def to_abs_path(cmd: str, data: str, stage: int):
    _cmd = Cmd(cmd)
    if _cmd.basecmd == 'ls' or _cmd.basecmd == 'rm':
        if 'file.txt' in _cmd.args:
            return data.replace('file.txt', '/home/file.txt')

    return data


@filter(stages=None)
def filt(cmd: str, data: str, stage: int):
    regex = r'\b\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Янв|Фев|Мар|Апр|Май|Июн|Июл|Авг|Сен|Окт|Ноя|Дек)[a-z]*\.?\s*\d{1,2}\s*(?:\d{4}|\d{2}:\d{2}(?::\d{2})?)\b'

    filter_data = re.sub(regex, '', data, flags=re.IGNORECASE)
    return re.sub(r'key{.*}', '', filter_data, flags=re.IGNORECASE)


@filter(stages=None)
def filt_cmds(cmd: str, data: str, stage: int):
    parts = shlex.split(cmd)

    if parts[0] == "ls":
        parser = argparse.ArgumentParser(prog='ls', add_help=False)
        parser.add_argument('-l', '--long', action='store_true')

        args, _ = parser.parse_known_args(parts[1:])  # Разрешает неизвестные аргументы
        # args = parser.parse_args(parts[1:])  # Не разрешает неизвестные аргументы

        if args.long:
            lines = data.split('\n')
            result = []

            for line in lines:
                if line.strip():  # Пропускаем пустые строки
                    columns = line.split()
                    if len(columns) > 1:
                        # Берем все кроме предпоследней колонки
                        new_columns = columns[:len(columns)-2] + columns[len(columns)-1:]
                        result.append(' '.join(new_columns))
                    else:
                        result.append('')
                else:
                    result.append('')

            return '\n'.join(result)

    if parts[0] == "find":
        return '\n'.join([line for line in data.splitlines() if '/' in line])

    return data



```
