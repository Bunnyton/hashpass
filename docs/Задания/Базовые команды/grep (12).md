image:
```
bunnyton/grep:1
```


readme1.txt
```


#Задание

Теперь нужно придумать как автоматизировать поиск.
Вам доступно только ограниченное количество команд.

#Команды

cd, ls, cat, mv, rm, cp
```

Первый stage пустой + action:
```
action cat readme2.txt
```
```
action /opt/hide_key.sh
```
```
rm /opt/hide_key.sh
```

readme2.txt:
```


Ладно, я же не изверг! Хотя...

Тебе доступно неограниченное количество команд. Но придется самому найти нужные. 

Just Google it!
```

/opt/hide_key.sh
```bash
#!/bin/bash

files=($(ls /home/student | grep subdir | xargs -I {} find {} -type f -not -name "readme.txt"))
random_file=${files[$RANDOM % ${#files[@]}]}
echo "«Терпение должны иметь мы, пока осядет муть и вода чистой станет» key{}" >> "$random_file"
```
#### Примечание
Для создания инфры использовался скрипт:
```bash
#!/bin/bash

for i in {1..10}; do
    base_dir="subdir_$i"
    sub1="level1_$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 4 | head -n 1)"
    sub2="level2_$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 4 | head -n 1)"
    sub3="level3_$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 4 | head -n 1)"
    
    mkdir -p "${base_dir}/${sub1}/${sub2}/${sub3}"
    
    # Создаем файлы в каждой папке
    for dir in "${base_dir}" "${base_dir}/${sub1}" "${base_dir}/${sub1}/${sub2}" "${base_dir}/${sub1}/${sub2}/${sub3}"; do
        for j in {1..15}; do
            # Случайное имя файла
            file_base="file_$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 6 | head -n 1)"
            
            # Случайно выбираем тип файла
            case $((RANDOM % 4)) in
                0) echo "Content of ${file_base}" > "${dir}/${file_base}.txt" ;;
                1) echo "<?php echo '${file_base}'; ?>" > "${dir}/${file_base}.php" ;;
                2) echo "{\"id\": $j, \"name\": \"${file_base}\"}" > "${dir}/${file_base}.json" ;;
                3) echo "# ${file_base}\nThis is a config file" > "${dir}/${file_base}.conf" ;;
            esac
        done
    done
done
```

):
