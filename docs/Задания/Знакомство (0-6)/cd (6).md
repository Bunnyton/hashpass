image:
```
bunnyton/cd:latest
```

readme.txt:
```


В Linux существуют файлы и директории.

Как просмотреть обычный файл мы выяснили, но как из терминала перейти в другую директорию?

В системе с графической оболочкой, такой как windows, вы нажимаете 2 раза на папку, затем на следущую после нее.
В консоли же для перемещения Вам необходимо использовать команду cd.

Допустим, Вы находитесь в директории /home/user/ (аналог в windows C:\User\).
Чтобы перейти в каталог downloads внутри user необходимо ввести следующую команду:
cd /home/user/downloads

Но если вы находитесь в директории /home/user/project/admin_tool/mne/nujno/bolshe/papok/1/2/3/4/5/6, то чтобы перейти на директорию выше, вам придется ввести следующую команду:
cd /home/user/project/admin_tool/mne/nujno/bolshe/papok/1/2/3/4/5

Чтобы не писать каждый раз абсолютный путь используют относительные, то есть предыдущую задачу можно было бы решить так:
cd ../
А чтобы перейти в downloads:
cd ./downloads


Абсолютный путь текующей директории можно вывести используя команду:
pwd

#Задание 
Перейдите в директорию dir1/dir2/dir3/dir4/dir5/dir6/dir7/dir8/dir9/cd_to_me и выполните команду ls
```

infra:
```
mkdir -p dir1/dir2/dir3/dir4/dir5/dir6/dir7/dir8/dir9/cd_to_me
```

dir1/dir2/dir3/dir4/dir5/dir6/dir7/dir8/dir9/cd_to_me/key_here.txt
```

Ты думал все так просто?)

Нет, конечно, нет)))

Перейди в предыдущую директорию и введи pwd

```


action: 
```
action echo -e "\nТы же исползовал Tab, да? ;)"
```
```
action echo "Ты почти у цели, перейди теперь обратно, в key_here.txt найдешь свой ключ :)"
```
```
action echo "Хватит ходить туда-сюда, нужно двигаться дальше!" > /home/student/dir1/dir2/dir3/dir4/dir5/dir6/dir7/dir8/dir9/cd_to_me/key_here.txt 
```

/.hash/bin/hooks/all.py
```python
@command(stages=[0])
def cd_normal(cmd: str, stage: int):
    res = {"before": []
            , "cmd": [cmd]
            , "after": []}

    if shlex.split(cmd)[0] == 'cd':
        if len(cmd.split('/')) < 4 or not re.search(r"/home/student", cmd):
            res = {"before": ["echo -e \"no no no, mister fish!\nИспользуй абсолютный путь\"" ]
                    , "cmd": []
                    , "after": []}



    return res


@command(stages=[1])
def cd_normal2(cmd: str, stage: int):
    res = {"before": []
            , "cmd": [cmd]
            , "after": []}

    if shlex.split(cmd)[0] == 'cd':
        proc_cmd = re.sub(r'\.\/', '', shlex.split(cmd)[1].strip('/'))
        if proc_cmd != '..':
            res = {"before": ["echo -e \"Так, ты правда решил что лучше будет использовать абсолютный путь?\"" ]
                    , "cmd": []
                    , "after": []}


	return res
```
