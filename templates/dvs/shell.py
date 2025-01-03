import sys
import os
import subprocess
import re
import shlex

from datetime import datetime

import taskclient

class Color():
    GREEN="\033[01;32m"
    BLUE="\033[01;34m"
    WHITE="\033[01;97m" 
    RESET="\033[0;0m"


    def green(s: str):
        return ''.join([Color.GREEN, s, Color.RESET])


    def blue(s: str):
        return ''.join([Color.BLUE, s, Color.RESET])


    def white(s: str):
        return ''.join([Color.WHITE, s, Color.RESET])




class Config():
    def __init__(self):
        self.cmdfile="/.hash/.hash.cmd"
        self.cmdoutfile="/.hash/.hash.cmd.out"
        self.tmpfile="/.hash/.hash.tmp"
        self.logfile="/.hash/.hash.log"
        self.pwdfile="/.hash/.hash.pwd"
        self.statusfile="/.hash/.hash.status"

        self.prevdir = os.getcwd()
        self.curdir = os.getcwd()
        self.homedir = os.path.expanduser('~')

        self.historyfile= os.path.join(self.homedir, ".bash_history")

        self.fullhostname = self.get_name()


    def get_hostname(self):
        res = subprocess.run(["hostname"], capture_output=True, text=True)
        if res.stdout:
            return ''.join(res.stdout).strip()

        else:
            return "unknown"

    def get_name(self):
        return '@'.join([os.getenv("USER", "unknown"), self.get_hostname()])


    def get_time(self):
        return datetime.now().strftime("%H:%M:%S")


    def get_promptdir(self):
        return re.sub(r'^' + self.homedir, '~', self.curdir)



def prompt(config):
    res = ''.join([Color.green(config.fullhostname), ' in ', Color.blue(config.get_promptdir()), '\n'])
    res += ''.join(['[', config.get_time(), ']', Color.white('ξ'), ' '])
    return res


def split_command(command):
    """
    Разделяет команду на элементы с учетом кавычек и разделителей, игнорируя разделители внутри кавычек.
    Строки внутри кавычек восстанавливаются в виде отдельных элементов с кавычками.
    Команды перед разделителями собираются в отдельные списки.

    :param command: Строка команды.
    :return: Список аргументов с подсписками для команд.
    """
    result = []
    temp = []
    in_quotes = False
    quote_char = None  # Тип кавычек (одинарные или двойные)

    i = 0
    while i < len(command):
        char = command[i]

        # Если встречаем кавычку, начинаем или заканчиваем строку в кавычках
        if char in ["'", '"']:
            if not in_quotes:
                in_quotes = True
                quote_char = char
                temp.append(char)  # Добавляем кавычку в начало
            elif in_quotes and char == quote_char:
                in_quotes = False
                temp.append(char)  # Добавляем закрывающую кавычку
                result.append(''.join(temp))  # Завершаем аргумент как строку
                temp = []  # Очищаем временный список
        elif in_quotes:
            temp.append(char)  # Собираем символы внутри кавычек
        elif char in [' ', '\t', '\n']:  # Пропускаем пробелы
            if temp:
                result.append(''.join(temp))  # Завершаем аргумент
                temp = []
        elif command[i:i+2] in ['&&', '||']:  # Если нашли специальные символы (например, &&)
            if temp:
                result.append(''.join(temp))  # Добавляем команду перед разделителем
                temp = []
            result.append(command[i:i+2])  # Добавляем сам разделитель
            i += 1  # Пропускаем второй символ
        elif command[i:i+1] in [';', '|']:  # Разделители команд
            if temp:
                result.append(''.join(temp))  # Добавляем команду перед разделителем
                temp = []
            result.append(command[i:i+1])  # Добавляем сам разделитель
        else:
            temp.append(char)  # Собираем символы в аргумент

        i += 1

    # Добавляем оставшийся аргумент, если он есть
    if temp:
        result.append(''.join(temp))

    # Формируем финальный список, где команды перед разделителями будут в подсписках
    final_result = []
    temp_list = []

    for item in result:
        if item in ['&&', ';', '||']:  # Если это разделитель, добавляем подсписок для предыдущей команды
            if temp_list:
                final_result.append(temp_list)  # Завершаем текущий список команды
                temp_list = []  # Очищаем временный список для команды
            final_result.append(item)  # Добавляем сам разделитель
        else:
            temp_list.append(item)  # Добавляем аргумент в текущую команду

    # Добавляем последнюю команду, если она есть
    if temp_list:
        final_result.append(temp_list)

    return final_result


def input_cmd(config):
    while True:
        subprocess.run(["fish", "-ic", ';'.join([' '.join(["read -SP", '"' + prompt(config) + '"', "cmd"]), ' '.join(["echo $cmd >", config.cmdfile])])])

        with open(config.cmdfile, 'r') as cf:
            cmd = cf.read().strip()
            if cmd: 
                return split_command(cmd)


def search_cmd(cmd: list, search_cmd: list): # without argument features
    if search_cmd:
        for part in cmd:
            if isinstance(part, list) and part == search_cmd:
                return True
    return False


def search_subcmd(cmd: list, subcmd: list):
    if subcmd:
        for part in cmd:
            if isinstance(part, list) and len(subcmd) < len(part):
                for offset in range(len(part) - len(subcmd) + 1):
                    if part[offset] == subcmd[0] and part[offset : offset + len(subcmd)] == subcmd:
                        return True
    return False


def replace_cmd(cmd: list, search_cmd: list, replace_cmd: list):
    if search_cmd:
        for i, part in enumerate(cmd):
            if isinstance(part, list) and part == search_cmd:
                cmd[i] = replace_cmd
    return cmd


def main():
    if len(sys.argv) > 1:
        subprocess.run(["/usr/bin/bash", *sys.argv[1::]])

    else:
        config = Config()
        while True:
            try:
                cmd = input_cmd(config)
                cmdstr = ' '.join(' '.join(x) if isinstance(x, list) else x for x in cmd)

                if search_cmd(cmd, ["task", "exit"]):
                    taskclient.handle_cmd(["exit"])
                    sys.exit()

                if search_cmd(cmd, ["exit"]):
                    sys.exit()

                with open(config.logfile, 'a') as lf:
                    lf.write("----------------------------------------------")
                    lf.write(''.join([prompt(config), cmdstr]))
                    lf.write("----------------------------------------------")

                with open(config.historyfile, 'a') as hf:
                    hf.write(cmdstr)

                if search_subcmd(cmd, ["cd"]):
                    cmd = replace_cmd(cmd, ["cd", "-"], ["cd", config.prevdir])
                    cmdstr += " ; " 
                    cmdstr += ' '.join(["pwd", ">", config.pwdfile])

                cmds = taskclient.handle_cmd(["cmd", cmdstr])
                if not cmds:
                    cmds = {"before": [],
                            "cmd": [cmdstr],
                            "after": []}

                for cmd_group in [cmds["before"], cmds["cmd"], cmds["after"]]:
                    for cmd in cmd_group:
                        print(cmd)
                        subprocess.run(["script", "-qc", ' '.join(["/usr/bin/bash -ic", "'", cmd, "'"]), config.tmpfile]) # the last command change file

                with open(config.tmpfile, 'r') as tf:
                    clear_out = tf.readlines()[1:-1]
                    with open(config.cmdoutfile, 'w') as cof:
                        cof.writelines(clear_out)
                    with open(config.logfile, 'a') as lf:
                        lf.writelines(clear_out)
                        lf.write("##############################################")

                with open(config.pwdfile, 'r') as pf:
                    pwd = pf.read().strip()
                    if pwd:
                        config.prevdir = config.curdir
                        config.curdir = pwd
                        os.chdir(pwd)

                if os.path.exists("/etc/systemd/system/taskchecker.service"):
                    taskclient.handle_cmd(["check"])

            except Exception as e:
                raise
                print(e)
                break
                pass


if __name__ == "__main__":
    main()
