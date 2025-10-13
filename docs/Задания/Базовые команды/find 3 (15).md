image:
```
bunnyton/find:3
```

Основан на [[bunnyton_find_base]]

readme.txt
```


#Задание 
Найдите все директории 4 уровня при помощи -name
```


#### Решение
```
find . -type d -name "level4*"
```

/.hash/dvs/hooks/all.py
```python

@check(stages=None)
def check_name(cmd: str, stage: int):
	if "name" not in cmd:
		return False
```
