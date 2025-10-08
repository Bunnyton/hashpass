#!/bin/python3

from tabulate import tabulate

from hashpass.settings import Settings
from hashpass.userconfig import UserConfig
from hashpass.key import calc_key

settings = Settings()
userconfig = UserConfig()

username = input("Введите имя пользователя: ").strip()

task_key = [["TASK", "KEY"]]
for task in userconfig.get_task_name(all=True):
    key = calc_key(settings.masterkey + username + task)
    task_key.append([task, key])


print(tabulate(task_key, headers="firstrow", tablefmt="grid"))
