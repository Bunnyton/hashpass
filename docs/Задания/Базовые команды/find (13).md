image:
```
bunnyton/find:1
```


readme.txt
```


Команда find используется для поиска файлов и директорий

#Команда
find имеет следующий вид
find dir -keys

Например:
find /home/user/ -name "*.txt"

'*' соответсвует любой последовательности символов. Обратите внимание, что ключи в find записываются не совсем стандартно, несмотря на то, что они являются словами, они пишутся с одним дефисом

find имеет несколько очень интересных ключей, например, очень удобно использовать ограничение по поиску в глубину
find . -maxdepth 4 -name "*.txt"

. здесь означает текущую директорию

Как можно заметить в предыдущем примере, в find можно накладывать более одного параметра поиска, тогда это соответсвует "и".

Также можно использовать и ключ -o, что соответствует "или".
find . -maxdepth 4 -iname "abc*" -o -name "cba*"

Причем, -maxdepth не будет накладываться на оба условия 
Или cba* или maxdpeth 4 и abc*

#Задание 
Найдите в директории search все файлы и директории, которые находятся не выше 3 уровня вложенности
```

```
action echo -e "\nЭто только начало..."
```

#### Решение
```
find source -maxdepth 3
```

/.hash/dvs/hooks/all.py
```python
@command(stages=None)
def cmd_blacklist(cmd: str, stage: int):
    if shlex.split(cmd)[0] == 'cd':
        res = {"before": ["echo \"Куда собрался??? Придется тебе остаться здесь!\""]
                , "cmd": []
                , "after": []}

    else:
        res = {"before": []
                , "cmd": [cmd]
                , "after": []}

    return res

```
#### Примечание
Для создания инфры использовался скрипт:
```bash
#!/bin/bash

for i in $(seq 0 4)
do
	mkdir level1_$i
	touch level1_$$${i}
done

for j in $(seq 1 4)
do
	for i in $(seq 0 4)
	do
		find . -type d -mindepth $j -maxdepth $j | xargs -I {} mkdir {}/level$((j+1))_$i
		find . -type d -maxdepth $j -mindepth $j | xargs -I {} touch {}/level$((j+1))_$$${i}
	done
done
```
