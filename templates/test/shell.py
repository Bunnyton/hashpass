import sys
import os
import subprocess
import re

from datetime import datetime

import taskclient

class Color():
    GREEN="\033[01;32m"
    RESET="\033[0;0m"
    BLUE="\033[01;34m"
    WHITE="\033[01;97m"


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


def input_cmd(config):
    while True:
        subprocess.run(["fish", "-ic", ';'.join([' '.join(["read -SP", '"' + prompt(config) + '"', "cmd"]), ' '.join(["echo $cmd >", config.cmdfile])])])

        with open(config.cmdfile, 'r') as cf:
            cmd = cf.read().strip()
            if cmd:
                return cmd




def main():
    if len(sys.argv) > 1:
        subprocess.run(["/usr/bin/bash", *sys.argv[1::]])

    else:
        config = Config()
        while True:
            try:
                cmd = input_cmd(config)

                if re.search(r"^\s*task\s+exit\b\s*", cmd):
                    taskclient.handle_cmd(["exit"])
                    sys.exit()

                if re.search(r"^\s*\bexit\b\s*", cmd):
                    sys.exit()

                with open(config.logfile, 'a') as lf:
                    lf.write("----------------------------------------------")
                    lf.write(''.join([prompt(config), ' '.join(cmd)]))
                    lf.write("----------------------------------------------")

                with open(config.historyfile, 'a') as hf:
                    hf.write(cmd)

                if re.search(r"\bcd\b\s+\-\s+|\bcd\b\s+\-$", cmd):
                    cmd = re.sub(r"\bcd\b\s+\-\s+|\bcd\b\s+\-$", ' '.join(["cd", config.prevdir]), cmd)
                    cmd += "; pwd > " + config.pwdfile

                elif re.search(r"\bcd\b", cmd):
                    cmd += "; pwd > " + config.pwdfile

                cmds = taskclient.handle_cmd(["cmd", cmd])
                for cmd in cmds:
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

                if os.path.exists("/usr/bin/taskcheckerserver"):
                    taskclient.handle_cmd(["check"])

            except Exception as e:
                print(e)
                break
                pass


if __name__ == "__main__":
    main()
