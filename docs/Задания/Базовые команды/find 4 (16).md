image:
```
bunnyton/find:4
```

Основан на [[bunnyton_find_base]]


readme.txt
```


#Задание 
Найдите все файлы, которые начинаются с level2 или содержат в названии "3"
```


#### Решение
```
find . -name "level2*" -type f -o -name "*3*" -type f 
```

