from hooks.engine import *

import re
import argparse
import shlex


# @command(stages=None)
# def cmd_whitelist(cmd: str, stage: int):
#     if shlex.split(cmd)[0] != 'ls':
#         res = {"before": ["echo \"This command is on the blacklist\""]
#                 , "cmd": []
#                 , "after": []}
# 
#     else:
#         res = {"before": ["echo \"This command is not on the blacklist\""]
#                 , "cmd": [cmd]
#                 , "after": []}
# 
#     return res


# @command(stages=None)
# def cmd_blacklist(cmd: str, stage: int):
# 
#     primary_cmd = shlex.split(cmd)[0]
# 
#     if primary_cmd == 'grep':
#         res = {"before": ["echo \"This command is on the blacklist\""]
#                 , "cmd": []
#                 , "after": []}
# 
#     elif primary_cmd == 'find':
#         res = {"before": ["echo \"This command is on the blacklist\""]
#                 , "cmd": []
#                 , "after": []}
# 
#     else:
#         res = {"before": []
#                 , "cmd": [cmd]
#                 , "after": []}
# 
#     return res


# @command(stages=[0, 1])
# def cmd_ls(cmd: str, stage: int):
#     primary_cmd = shlex.split(cmd)[0]
#     if primary_cmd == "ls":
#         res = {"before": ["echo \"Успех\""]
#                 , "cmd": [cmd]
#                 , "after": []}
# 
#     else:
#         res = {"before": []
#                 , "cmd": [cmd]
#                 , "after": []}
# 
#     return res


@filter(stages=None)
def filt(cmd: str, data: str, stage: int):
    regex = r'\b\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Янв|Фев|Мар|Апр|Май|Июн|Июл|Авг|Сен|Окт|Ноя|Дек)[a-z]*\.?\s*\d{1,2}\s*(?:\d{4}|\d{2}:\d{2}(?::\d{2})?)\b'

    filter_data = re.sub(regex, '', data, flags=re.IGNORECASE)
    return re.sub(r'key{.*}', '', filter_data, flags=re.IGNORECASE)


@filter(stages=None) 
def filt_ls_l(cmd: str, data: str, stage: int):
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

    return data


# @check(stages=None)
# def check_man(cmd: str, stage:int):
#     parts = shlex.split(cmd)
#     
#     if parts[0] == "man":
#         parser = argparse.ArgumentParser(add_help=False)
#         parser.add_argument('pages', nargs='*')
#         
#         args, _ = parser.parse_known_args(parts[1:])
# 
#         if len(args.pages) == 1 and 'man' in args.pages:
#             return True

