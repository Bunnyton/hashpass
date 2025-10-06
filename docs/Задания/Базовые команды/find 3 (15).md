image:
```
bunnyton/find:3
```


readme.txt
```


#Задание 
Найдите все директории 4 уровня при помощи -name
```


#### Решение
```
find source -name "level4*"
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
