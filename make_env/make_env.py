#!/bin/python3

import sys
import os
import uuid
import subprocess
import toml
import tty
import termios
import glob
import time

import shutil
from pathlib import Path
from tqdm import tqdm

from multiprocessing import Process

from tabulate import tabulate


def copy(src, dest, progress_bar=False):
    try:
        if not os.path.isfile(src):
            src = src + '/'
            dest = dest + '/'

        if progress_bar:
            subprocess.run(["rsync", "-a", "-l", "--info=progress2", src, dest])
        else:
            subprocess.run(["rsync", "-a", "-l", src, dest])

    except Exception:
        if not os.path.isfile(src):
            shutil.rmtree(dest_dir)

        raise
        



def read(s: str):
    val = input(s)
    if not val:
        raise Exception("Value can't be empty")

    return val


def get_char():
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


def get_answer(question):

    ans = ''
    while ans != 'y' and ans != 'n':
        print(question, end=' [y/n] ')
        ans = get_char()
    
    return ans


class Image():
    class Config():
        config_dir = "/home/anton/LinuxWork/study/8/make_env/config/images"
        config_filename = "manifest.toml"
    

    def __init__(self, param=None):
        if not os.path.exists(Image.Config.config_dir):
            os.makedirs(Image.Config.config_dir)

        self.id : str
        self.name : str
        self.author : str
        self.version : str
        self.layers : list

        image: list
        if param is not None:
            if ':' in param:
                image = Image.get(name=param.split(':')[0], version=param.split(':')[1])

            else:
                image = Image.get(id=param)
                if image:
                    image = image[0]

                    self.id = image['image']['id']
                    self.name = image['image']['name']
                    self.author = image['image']['author']
                    self.version = image['image']['version']
                    self.layers = image['image']['layers']
                else:
                    raise Exception("Can't find image")

        




    def edit(self):
        container = Container(self)
        container.start(is_edit_image_mode=True)


    def create(self, param=None):

        if param is None:
            # FIXME update tree with exists image
            self.name = str(read("Enter name of image: "))
            self.author = str(read("Enter author of image: "))
            self.version = str(read("Enter version of image: "))
            self.id = str(uuid.uuid4()).replace("-", "")
            self.layers = list()

            self.save(is_base_image=True)

        else:
            parent_image: list
            if ':' in param:
                parent_image = Image.get(name=param.split(':')[0], version=param.split(':')[1])
            else:
                parent_image = Image.get(id=param)
            if parent_image:
                parent_image = parent_image[0]

                self.name = str(read("Enter name of image: "))
                self.author = str(read("Enter author of image: "))
                self.version = str(read("Enter version of image: "))
                self.id = str(uuid.uuid4()).replace("-", "")

                self.layers = parent_image['image']['layers']
                self.layers.append(parent_image['image']['id'])

                self.save()
            else:
                raise Exception("Can't find some image")

        return self.id


    def save(self, is_base_image=False):
        data = dict()
        if os.path.exists(Image.Config.config_filename):
            data = toml.load(Image.Config.config_filename)

        else:
            data["image"] = dict()

        data["image"]["name"] = self.name
        data["image"]["author"] = self.author
        data["image"]["version"] = self.version
        data["image"]["id"] = self.id
        data["image"]["layers"] = self.layers

        with open(Image.Config.config_filename, "w") as f:
            toml.dump(data, f)

        if is_base_image:
            # shutil.copytree(os.getcwd(), Image.Config.config_dir + '/' + self.id)
            copy(os.getcwd(), Image.Config.config_dir + '/' + self.id, progress_bar=True)
        else:
            copy(Image.Config.config_filename, Image.Config.config_dir + '/' + self.id + '/')


    def get(id=None, name=None, version=None):
        data = list()
        if id is None:
            if name is None:
                for file in glob.glob(Image.Config.config_dir + "/**/" + Image.Config.config_filename, recursive=False):
                    data.append(toml.load(file))

            elif version is not None:
                for file in glob.glob(Image.Config.config_dir + "/**/" + Image.Config.config_filename, recursive=False):
                    temp = toml.load(file)

                    if temp['image']['name'] == name and temp['image']['version'] == version:
                        return [temp]

            else:
                raise Exception("Version can't be empty")

        else:
                for file in glob.glob(Image.Config.config_dir + "/**/" + Image.Config.config_filename, recursive=False):
                    temp = toml.load(file)

                    if temp['image']['id'] == id:
                        return [temp]

        return data


    def list():

        table = [["ID", "NAME", "VERSION"]]

        for data in Image.get():
           table.append([data["image"]["id"], data["image"]["name"], data["image"]["version"]])

        print(tabulate(table, headers="firstrow", tablefmt="grid"))




class Container():
    class Config():
        config_dir = "/home/anton/LinuxWork/study/8/make_env/config/containers"
        templates_dir = "/home/anton/LinuxWork/study/8/make_env/templates"
        config_filename = "manifest.toml"


    def __init__(self, image: Image):
        if not os.path.exists(Container.Config.config_dir):
            os.makedirs(Container.Config.config_dir)

        self.id = str(uuid.uuid4()).replace("-", "")
        self.image = image
        self.status = "created" #FIXME
        self.save()

        self.config_dir = '/'.join([Container.Config.config_dir, self.id])
        self.mountpoint = self.config_dir + "/mountpoint"

        self._hash_config_dir = '/'.join([self.mountpoint, ".hash"])
        self._hash_logfile = '/'.join([self._hash_config_dir, ".hash.log"])
        self._hash_cmdfile = '/'.join([self._hash_config_dir, ".hash.cmd"])
        self._hash_cmdoutfile = '/'.join([self._hash_config_dir, ".hash.cmd.out"])
        self._statusfile = '/'.join([self._hash_config_dir, ".hash.status"])
        self._hash_signal_string = "hash"


    def save(self):
        if not os.path.exists('/'.join([Container.Config.config_dir, self.id])):
            os.makedirs('/'.join([Container.Config.config_dir, self.id]))
        else:
            raise Exception(" dir already exist, rm this and try again")

        data = dict()
        data["container"] = dict()
        data["container"]["id"] = self.id
        data["container"]["image"] = self.image.id
        data["container"]["status"] = self.status

        with open('/'.join([Container.Config.config_dir, self.id, Container.Config.config_filename]), "w") as f:
            toml.dump(data, f)


    def _configurate(self, is_edit_image_mode: bool):
        if not os.path.exists('/'.join([self.mountpoint, ".hash"])):
            os.makedirs(self._hash_config_dir)
        with open(self._hash_logfile, "a") as f:
            pass # make file 
        with open(self._hash_cmdfile, "a") as f:
            pass # make file 
        with open(self._hash_cmdoutfile, "a") as f:
            pass # make file 
        with open(self._statusfile, "w") as f:
            f.write("created\n")

        os.chmod(self._hash_config_dir, 0o777)
        os.chmod(self._hash_logfile, 0o666)
        os.chmod(self._hash_cmdfile, 0o666)
        os.chmod(self._hash_cmdoutfile, 0o666)
        os.chmod(self._statusfile, 0o666)

        if os.path.exists('/'.join([self.mountpoint, "usr", "bin", "task"])):
            os.remove('/'.join([self.mountpoint, "usr", "bin", "task"]))
        copy('/'.join([Container.Config.templates_dir, "task.py"])
              , '/'.join([self.mountpoint, "usr", "bin", "task"]))
        os.chmod('/'.join([self.mountpoint, "usr", "bin", "task"]), 0o555)

        if not is_edit_image_mode:
            if os.path.exists('/'.join([self.mountpoint, "usr", "bin", "hash"])):
                os.remove('/'.join([self.mountpoint, "usr", "bin", "hash"]))
            copy('/'.join([Container.Config.templates_dir, "hash.sh"])
                  , '/'.join([self.mountpoint, "usr", "bin", "hash"]))
            os.chmod('/'.join([self.mountpoint, "usr", "bin", "hash"]), 0o555)

            with open('/'.join([self.mountpoint, "etc", "bash.bashrc"]), "a+") as f:
                for line in reversed(f.readlines()):
                    if line != "bash -i /usr/bin/hash":
                        continue
                    break

                else:
                    conf_lines = list()

                    conf_lines.append("alias bash=\"bash -i /usr/bin/hash\"")
                    conf_lines.append("alias alert='notify-send --urgency=low -i \"$([ $? = 0 ] && echo terminal || echo error)\" \"$(history|tail -n1|sed -e '\\''s/^\s*[0-9]\+\s*//;s/[;&|]\s*alert$//'\\'')\"'")
                    conf_lines.append("alias egrep=\"egrep --color=auto\"")
                    conf_lines.append("alias fgrep=\"fgrep --color=auto\"")
                    conf_lines.append("alias grep=\"grep --color=auto\"")
                    conf_lines.append("alias l=\"ls -CF\"")
                    conf_lines.append("alias la=\"ls -A\"")
                    conf_lines.append("alias ll=\"ls -alF\"")
                    conf_lines.append("alias ls=\"ls --color=auto\"")
                    conf_lines.append("alias ls=\"ls --color=auto\"")
                    conf_lines.append("echo \"started\" > /.hash/.hash.status")

                    conf_lines.append("if [[ -z \"$(cat ~/.config/fish/config.fish | grep 'set fish_greeting')\" ]]; then")
                    conf_lines.append("\techo \"set fish_greeting\" >> ~/.config/fish/config.fish")
                    conf_lines.append("fi")

                    conf_lines.append("if [[ ! -f ~/.hash && -z \"$(cat /.hash/.hash.status | grep stop)\" ]]; then")


                    conf_lines.append("\ttouch ~/.hash")
                    conf_lines.append("\tbash")
                    conf_lines.append("\trm ~/.hash")

                    conf_lines.append("fi")

                    for line in conf_lines:
                        f.write(line + " # " + self._hash_signal_string + "\n")


    def _deconfigurate(self):
        shutil.rmtree(self._hash_config_dir)
        if os.path.exists('/'.join([self.mountpoint, "usr", "bin", "hash"])):
            os.remove('/'.join([self.mountpoint, "usr", "bin", "hash"]))
        if os.path.exists('/'.join([self.mountpoint, "usr", "bin", "task"])):
            os.remove('/'.join([self.mountpoint, "usr", "bin", "task"]))

        deconf_lines: list
        with open('/'.join([self.mountpoint, "etc", "bash.bashrc"]), "a+") as f:
            lines = f.readlines()
            deconf_lines = [line for line in lines if self._hash_signal_string not in line]

        with open('/'.join([self.mountpoint, "etc", "bash.bashrc"]), 'w') as f:
            f.writelines(deconf_lines)



    def _mount(self, is_edit_image_mode: bool):
        workdir = self.config_dir + "/work"
        for dir in [workdir, self.mountpoint]:
            if not os.path.exists(dir):
                os.makedirs(dir)

        upperdir: str
        lowerdir: str

        lowerdir = list()

        for layer in self.image.layers:
            lowerdir.append(Image.Config.config_dir + '/' + layer)

        if is_edit_image_mode:
            upperdir = Image.Config.config_dir + '/' + self.image.id

        else:
            lowerdir.append(Image.Config.config_dir + '/' + self.image.id)
            upperdir = self.config_dir + '/' + "emptyupper"
            if not os.path.exists(upperdir):
                os.makedirs(upperdir)

        if not lowerdir:
            lowerdir = self.config_dir + '/' + "emptylower"
            if not os.path.exists(lowerdir):
                os.makedirs(lowerdir)

        else:
            lowerdir = ':'.join(lowerdir)


        subprocess.run([ "mount", "overlay", "-t", "overlay", 
                                  "-o", ','.join(["lowerdir=" + lowerdir
                                      , "upperdir=" + upperdir , "workdir=" + workdir]),
                                self.mountpoint], check=True)


    def _umount(self):
        subprocess.run([ "umount", self.mountpoint], check=True)


    def get_status(self):
        if not os.path.exists(self._statusfile):
            return "deleted"

        else:
            status = subprocess.run(["machinectl", "status", self.id] 
                                            , capture_output=True, text=True)
            if status.stderr:
                return "deleted" # never

            with open(self._statusfile, "r") as f:
                return f.read().strip()


    def _monitoring(self):
        while True:
            time.sleep(1)
            status = self.get_status()
            if status == "stopping":
                time.sleep(1)
                subprocess.run([ "machinectl", "poweroff", self.id], check=True) #FIXME
                return
            elif status == "stopped" or status == "deleted":
                return



    def start(self, is_edit_image_mode=False):
        if self.id:
            self._mount(is_edit_image_mode)
            try:
                self._configurate(is_edit_image_mode)

                proc = Process(target=self._monitoring)
                proc.start()

                subprocess.run([ "systemd-nspawn", "-b", "-q"
                                                         , "-M", self.id
                                                         , "--user", "root"
                                                         , "-D", self.mountpoint], check=True) # True or False #FIXME
            except:
                raise

            finally:
                self._deconfigurate()
                self._umount()
                res = subprocess.run(["machinectl", "status", self.id] 
                                                , capture_output=True, text=True)
                if res.stdout:
                    time.sleep(1)
                    subprocess.run([ "machinectl", "poweroff", self.id], check=True)


                



def main():
    if len(sys.argv) == 2:
        image: Image
        if sys.argv[1] == "new":
            image = Image()
            image.create()
        else:
            raise Exception("Unknown argument")

    elif len(sys.argv) == 3:
        if sys.argv[1] == "new":
            image = Image()
            image.create(sys.argv[2])
            image.edit()

        elif sys.argv[1] == "edit":
            image = Image(sys.argv[2])
            image.edit()

        elif sys.argv[1] == "start":
            image = Image(sys.argv[2])
            container = Container(image)
            container.start()

        else:
            raise Exception("Unknown argument")

    elif len(sys.argv) == 1:
        Image.list()

    else:
        raise Exception("Incorrect arguments num")


if __name__ == "__main__":
    # Проверка, запущена ли программа с правами суперпользователя
    if os.geteuid() != 0:
        print("Эта программа должна быть запущена с правами суперпользователя. Используйте 'sudo'.")
        sys.exit(1)  # Завершение программы с кодом 1 (ошибка)
    
    main()
