image:
```
bunnyton/ls_mv_cp:1
```


readme.txt:
```


#Задание

Найдите в случайных текстовых файлах пароль к следующему заданию.
Вам доступно только ограниченное количество команд.

#Команды

cd, ls, cat, mv, rm, cp

#Подсказка 
Попробуйте удалять ненужные папки или файлы при помощи rm -rf
r - recursive f - force - рекурсивно удали все файлы в каталоге не спрашивая
Можно выводить содержимое сразу нескольких файлов при помощи cat ./*
Используйте <tab> для автодополнения названий файлов 
```
Для белого списка 
/.hash/dvs/hooks/all.py
```python
@command(stages=None)

def cmd_whitelist(cmd: str, stage: int):
    primary_cmd = shlex.split(cmd)[0]

    if primary_cmd not in ["cd", "ls", "cat", "mv", "rm", "cp"]:
        res = {"before": []
                , "cmd": [cmd]
                , "after": []}

    else:
        res = {"before": ["echo \"Эту команду нельзя использовать\""]
                , "cmd": []
                , "after": []}

    return res
```

#### Примечание
Для создания инфры использовался скрипт:
```bash
#!/bin/bash

for i in {1..4}; do
    base_dir="subdir_$i"
    sub1="level1_$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 4 | head -n 1)"
    sub2="level2_$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 4 | head -n 1)"
    sub3="level3_$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 4 | head -n 1)"
    
    mkdir -p "${base_dir}/${sub1}/${sub2}/${sub3}"
    
    # Создаем файлы в каждой папке
    for dir in "${base_dir}" "${base_dir}/${sub1}" "${base_dir}/${sub1}/${sub2}" "${base_dir}/${sub1}/${sub2}/${sub3}"; do
        for j in {1..3}; do
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

Для запрятывания ключа (первый stage пустой, далее action с выполнением):
/opt/hide_key.sh
```bash
#!/bin/bash

files=($(ls /home/student | grep subdir | xargs -I {} find {} -type f -not -name "readme.txt"))
random_file=${files[$RANDOM % ${#files[@]}]}
echo "«Терпение должны иметь мы, пока осядет муть и вода чистой станет» key{f2bf3954874ecebd}" >> "$random_file"
```
