image:
```
bunnyton/find:4
```


readme.txt
```


#Задание 
Найдите все непустые файлы в search
```


#### Решение
```
find . -not -empty -type f
```

```
action echo -e "\nВсе становится чуточку интереснее!))"
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
				find . -type d -maxdepth $j -mindepth $j | xargs -I {} bash -c "echo 'asdf' > {}/level$((j+1))_$j$j${i}"
	done
done
```
