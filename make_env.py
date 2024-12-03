#!/bin/python3

import sys
import os
import uuid
import subprocess
import toml
import glob
import time


from multiprocessing import Process

from tabulate import tabulate

from syshelp import copy,remove,move,read




class Image():
    class Config():
        config_dir = "/home/anton/LinuxWork/study/8/make_env/config/images"
        config_filename = "manifest.toml"
        hash_task_config_dirname = ".hash/.task"
        hash_task_config_filename = "config.toml"

    class Type():
        simple = "simple"
        task = "task"
        base = "base"
    

    def __init__(self, param=None):
        os.makedirs(Image.Config.config_dir, exist_ok=True)

        self.id : str
        self.name : str
        self.author : str
        self.version : str
        self.layers : list
        self.type: Image.Type
        
        image: list
        if param is not None:
            if ':' in param:
                image = Image.get(name=param.split(':')[0], version=param.split(':')[1])
                if not image:
                    raise Exception(' '.join(["Can't find image", param]))

            else:
                image = Image.get(id=param)
                if not image:
                    raise Exception(' '.join(["Can't find image with id =", param]))

            image = image[0]

            self.id = image['image']['id']
            self.name = image['image']['name']
            self.author = image['image']['author']
            self.version = image['image']['version']
            self.layers = image['image']['layers']
            self.type = image['image']['type']

            self.config_dir = os.path.join(Image.Config.config_dir, self.id)


    def edit(self):
        container = Container(self)
        container.start(mode=Container.Mode.image_edit)

    
    def create(self, param=None, is_task_image=False, name=None, author=None, version=None):
        if param is None:
            # FIXME update tree with exists image
            if is_task_image:
                raise Exception("Base image can't be a task")

        else:
            parent_image: list
            if ':' in param: # FIXME add id verification
                parent_image = Image.get(name=param.split(':')[0], version=param.split(':')[1])

            else:
                parent_image = Image.get(id=param)

            if parent_image:
                parent_image = parent_image[0]

                if is_task_image:
                    self.type = Image.Type.task

                else:
                    self.type = Image.Type.simple

                self.layers = parent_image['image']['layers']
                self.layers.append(parent_image['image']['id'])

            else:
                raise Exception("Can't find some image")

        if name is not None or author is not None or version is not None:
            if None in [name, author, version]:
                raise Exception("Image parameters are incorrect")

            self.name = name
            self.author = author
            self.version = version

        else:
            self.name = read("Enter name of image: ")
            self.author = read("Enter author of image: ")
            self.version = read("Enter version of image: ", default="latest")

        self.id = str(uuid.uuid4()).replace("-", "")


        self.config_dir = os.path.join(Image.Config.config_dir, self.id)

        self.save()

        return self.id


    def delete(self):
        if os.path.exists(self.config_dir):
            remove(self.config_dir)


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
        data["image"]["type"] = self.type
        data["image"]["layers"] = self.layers

        with open(Image.Config.config_filename, "w") as f:
            toml.dump(data, f)

        if is_base_image:
            copy(os.getcwd(), self.config_dir, progress_bar=True)

        else:
            move(Image.Config.config_filename, self.config_dir + '/')


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

        table = [["ID", "NAME", "VERSION", "TYPE"]]

        for data in Image.get():
           table.append([data["image"]["id"], data["image"]["name"], data["image"]["version"], data["image"]["type"]])

        print(tabulate(table, headers="firstrow", tablefmt="grid"))


    def load_task_config(self, path: str):
        if self.type == Image.Type.task:
            config = toml.load(path)
            copy(path, os.path.join(self.config_dir, Image.Config.hash_task_config_dirname, Image.Config.hash_task_config_filename))

        else:
            raise Exception(' '.join(["Image id =", self.id, "is not task image"]))




class Container():
    class Config():
        config_dir = "/home/anton/LinuxWork/study/8/make_env/config/containers"
        templates_dir = "/home/anton/LinuxWork/study/8/make_env/templates"
        config_filename = "manifest.toml"


    class Mode():
        image_edit = "Editing image environment for tasks"
        task_complete = "Completing a task"
        task_create = "Creating a task"

    class Status():
        created = "Container with task has been created, but not started"
        started = "Container with task has been started"
        stopping = "Container stopping"
        stopped = "Container with task has been stopped"
        deleted = "Container with task has been deleted or doesn't exist"


        def get_from(status_item):
            status_text: str
            if '/' in status_item or '.' in status_item or os.path.isfile(status_item):
                with open(status_item, 'r') as f:
                    status_text = f.read().strip()

            else:
                status_text = status_item

            if status_text == "created":
                return Container.Status.created

            elif status_text == "started":
                return Container.Status.started

            elif status_text == "stopping":
                return Container.Status.stopping

            elif status_text == "stopped":
                return Container.Status.stopped

            elif status_text == "deleted":
                return Container.Status.deleted

            else:
                raise Exception("Can't read a some status from text or file")


    def __init__(self, image: Image):
        os.makedirs(Container.Config.config_dir, exist_ok=True)

        self.id = str(uuid.uuid4()).replace("-", "")
        self.image = image

        self.config_dir = os.path.join(Container.Config.config_dir, self.id)
        self.mountpoint = os.path.join(self.config_dir, "mountpoint")

        self._hash_config_dir = os.path.join(self.mountpoint, ".hash")
        self._hash_logfile = os.path.join(self._hash_config_dir, ".hash.log")
        self._hash_cmdfile = os.path.join(self._hash_config_dir, ".hash.cmd")
        self._hash_cmdoutfile = os.path.join(self._hash_config_dir, ".hash.cmd.out")
        self._hash_tmpfile = os.path.join(self._hash_config_dir, ".hash.tmp")
        self._hash_pwdfile = os.path.join(self._hash_config_dir, ".hash.pwd")
        self._hash_signal_string = "hash"
        self._statusfile = os.path.join(self._hash_config_dir, ".hash.status")
        self._hash_task_config_dir = os.path.join(self._hash_config_dir, ".task")
        self._hash_task_config_filename = "config.toml"

        self.save()


    def save(self):
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)
        else:
            raise Exception("Dir already exist, rm this and try again")

        data = dict()
        data["container"] = dict()
        data["container"]["id"] = self.id
        data["container"]["image"] = self.image.id

        with open(os.path.join(self.config_dir, Container.Config.config_filename), "w") as f:
            toml.dump(data, f)


    def _configure(self, mode: Mode):
        os.makedirs(self._hash_config_dir, exist_ok=True)
        with open(self._hash_logfile, "a") as f:
            pass # make file 
        with open(self._hash_cmdfile, "a") as f:
            pass # make file 
        with open(self._hash_cmdoutfile, "a") as f:
            pass # make file 
        with open(self._hash_tmpfile, "a") as f:
            pass # make file 
        with open(self._hash_pwdfile, "a") as f:
            pass # make file 
        with open(self._statusfile, "w") as f:
            f.write("created\n")

        os.chmod(self._hash_config_dir, 0o777)
        os.chmod(self._hash_logfile, 0o666)
        os.chmod(self._hash_cmdfile, 0o666)
        os.chmod(self._hash_cmdoutfile, 0o666)
        os.chmod(self._hash_tmpfile, 0o666)
        os.chmod(self._hash_pwdfile, 0o666)
        os.chmod(self._statusfile, 0o666)

        copy(os.path.join(Container.Config.templates_dir, "dvs", "taskclient"), os.path.join(self.mountpoint, "usr", "bin", "task"))
        os.chmod(os.path.join(self.mountpoint, "usr", "bin", "task"), 0o555)

        if mode == Container.Mode.task_create:
            copy(os.path.join(Container.Config.templates_dir, "dvs", "taskcreatorserver"), os.path.join(self.mountpoint, "usr", "bin", "taskcreatorserver"))
            os.chmod(os.path.join(self.mountpoint, "usr", "bin", "taskcreatorserver"), 0o555)

            copy(os.path.join(Container.Config.templates_dir, "dvs", "taskcreator.service"), os.path.join(self.mountpoint, "etc", "systemd", "system", "taskcreator.service"))
            remove(os.path.join(self.mountpoint, "etc", "systemd", "system", "multi-user.target.wants", "taskcreator.service"))
            os.symlink(os.path.join("/", "etc", "systemd", "system", "taskcreator.service"), os.path.join(self.mountpoint, "etc", "systemd", "system", "multi-user.target.wants", "taskcreator.service"))

            copy(os.path.join(Container.Config.templates_dir, "dvs", "task_settings.toml"), os.path.join(self._hash_config_dir, "config", "task_settings.toml"))


        elif mode == Container.Mode.task_complete:
            copy(os.path.join(Container.Config.templates_dir, "dvs", "taskcheckerserver"), os.path.join(self.mountpoint, "usr", "bin", "taskcheckerserver"))
            os.chmod(os.path.join(self.mountpoint, "usr", "bin", "taskcheckerserver"), 0o555)

            copy(os.path.join(Container.Config.templates_dir, "dvs", "taskchecker.service"), os.path.join(self.mountpoint, "etc", "systemd", "system", "taskchecker.service"))

            remove(os.path.join(self.mountpoint, "etc", "systemd", "system", "multi-user.target.wants", "taskchecker.service"))
            os.symlink(os.path.join("/", "etc", "systemd", "system", "taskchecker.service"), os.path.join(self.mountpoint, "etc", "systemd", "system", "multi-user.target.wants", "taskchecker.service"))

        if mode != Container.Mode.image_edit:
            # if os.path.exists(os.path.join(self.mountpoint, "usr", "bin", "hash")):
            copy(os.path.join(Container.Config.templates_dir, "dvs", "shell")
                  , os.path.join(self.mountpoint, "usr", "bin", "hash"))
            os.chmod(os.path.join(self.mountpoint, "usr", "bin", "hash"), 0o555)
            if mode == Container.Mode.task_create:
                copy(os.path.join(Container.Config.templates_dir, "stage.sh")
                      , os.path.join(self.mountpoint, "usr", "bin", "stage"))
                os.chmod(os.path.join(self.mountpoint, "usr", "bin", "stage"), 0o555)


            with open(os.path.join(self.mountpoint, "etc", "bash.bashrc"), "a+") as f:
                f.seek(0)
                for line in reversed(f.readlines()):
                    if line.strip() != "/usr/bin/hash/hash":
                        continue
                    break

                else:
                    conf_lines = list()

                    conf_lines.append("alias bash=\"/usr/bin/hash/hash\"")
                    conf_lines.append("alias alert='notify-send --urgency=low -i \"$([ $? = 0 ] && echo terminal || echo error)\" \"$(history|tail -n1|sed -e '\\''s/^\s*[0-9]\+\s*//;s/[;&|]\s*alert$//'\\'')\"'")
                    conf_lines.append("alias egrep=\"egrep --color=auto\"")
                    conf_lines.append("alias fgrep=\"fgrep --color=auto\"")
                    conf_lines.append("alias grep=\"grep --color=auto\"")
                    conf_lines.append("alias l=\"ls -CF\"")
                    conf_lines.append("alias la=\"ls -A\"")
                    conf_lines.append("alias ll=\"ls -alF\"")
                    conf_lines.append("alias ls=\"ls --color=auto\"")

                    conf_lines.append("echo \"started\" > /.hash/.hash.status")

                    conf_lines.append("if [[ -z \"$(grep 'set fish_greeting' ~/.config/fish/config.fish 2> /dev/null)\" ]]; then")
                    conf_lines.append("\techo \"set fish_greeting\" >> ~/.config/fish/config.fish")
                    conf_lines.append("fi")

                    conf_lines.append("while [[ ! -f ~/.hash && -z \"$(grep stop /.hash/.hash.status 2> /dev/null)\" ]]; do")


                    conf_lines.append("\ttouch ~/.hash")
                    conf_lines.append("\tbash")
                    conf_lines.append("\trm ~/.hash 2> /dev/null")

                    conf_lines.append("done")

                    for line in conf_lines:
                        f.write(line + " # " + self._hash_signal_string + "\n")


    def _deconfigure(self):
        remove(self._hash_cmdfile)
        remove(self._hash_logfile)
        remove(self._hash_cmdoutfile)
        remove(self._hash_tmpfile)
        remove(self._statusfile)

        remove(os.path.join(self.mountpoint, "usr", "bin", "hash"))
        remove(os.path.join(self.mountpoint, "usr", "bin", "task"))
        remove(os.path.join(self.mountpoint, "usr", "bin", "stage"))
        remove(os.path.join(self.mountpoint, "usr", "bin", "taskcreatorserver"))
        remove(os.path.join(self.mountpoint, "usr", "bin", "taskcheckerserver"))
        remove(os.path.join(self.mountpoint, "usr", "bin", "taskclient"))
        remove(os.path.join(self.mountpoint, "etc", "systemd", "system", "taskchecker.service"))
        remove(os.path.join(self.mountpoint, "etc", "systemd", "system", "taskchecker.service"))
        remove(os.path.join(self.mountpoint, "etc", "systemd", "system", "multi-user.target.wants", "taskcreator.service"))
        remove(os.path.join(self.mountpoint, "etc", "systemd", "system", "multi-user.target.wants", "taskchecker.service"))

        deconf_lines: list
        with open(os.path.join(self.mountpoint, "etc", "bash.bashrc"), "r") as f:
            f.seek(0)
            lines = f.readlines()
            deconf_lines = [line for line in lines if self._hash_signal_string not in line]

        with open(os.path.join(self.mountpoint, "etc", "bash.bashrc"), 'w') as f:
            f.writelines(deconf_lines)


    def _mount(self, mode: Mode):
        workdir = os.path.join(self.config_dir, "work")
        for dir in [workdir, self.mountpoint]:
            os.makedirs(dir, exist_ok=True)

        upperdir: str
        lowerdir: str

        lowerdir = list()

        for layer in self.image.layers:
            lowerdir.append(os.path.join(Image.Config.config_dir, layer))

        if mode == Container.Mode.image_edit: 
            upperdir = self.image.config_dir

        else:
            lowerdir.append(self.image.config_dir)
            upperdir = os.path.join(self.config_dir, "emptyupper")
            os.makedirs(upperdir, exist_ok=True)

        if not lowerdir:
            lowerdir = os.path.join(self.config_dir, "emptylower")
            os.makedirs(lowerdir, exist_ok=True)

        else:
            lowerdir = ':'.join(lowerdir)

        subprocess.run([ "mount", "overlay", "-t", "overlay", 
                                  "-o", ','.join(["lowerdir=" + lowerdir
                                      , "upperdir=" + upperdir , "workdir=" + workdir]),
                                self.mountpoint], check=True)


    def _umount(self):
        subprocess.run([ "umount", self.mountpoint], check=True)


    def get_status(self):
        if os.path.exists(self._statusfile):
            return Container.Status.get_from(self._statusfile)

        else:
            sys_status = subprocess.run(["machinectl", "status", self.id] 
                                            , capture_output=True, text=True)
            if sys_status.stderr:
                return Container.Status.deleted # never

            else:
                raise Exception("Systemd container has been started, but status file doesn't exist")


    def stop(self):
        res = subprocess.run(["machinectl", "status", self.id] 
                                        , capture_output=True, text=True)
        if res.stdout:
            time.sleep(1)
            subprocess.run([ "machinectl", "poweroff", self.id], check=True)


    def _monitoring(self):
        while True:
            time.sleep(1)
            status: Container.Status
            try:
                status = self.get_status()

            except Exception:
                time.sleep(5)
                status = self.get_status()

            if status == Container.Status.stopping:
                self.stop()
                return

            elif status == Container.Status.stopped or status == Container.Status.deleted:
                return



    def start(self, mode=Mode.task_complete):
        if self.id:
            if mode == Container.Mode.task_complete:
                if self.image.type != Image.Type.task:
                    raise Exception(' '.join(["Image with id =", self.image.id, "is not task image"]))

            self._mount(mode)
            try:
                self._configure(mode)

                proc = Process(target=self._monitoring)
                proc.start()

                subprocess.run([ "systemd-nspawn", "-b", "-q"
                                                         , "-M", self.id
                                                         , "--user", "root"
                                                         , "-D", self.mountpoint], check=True) # True or False #FIXME
            except:
                raise

            finally:
                if mode == Container.Mode.task_create:
                    for config_file in glob.glob(self._hash_task_config_dir + "/*.toml", recursive=False):
                        config = toml.load(config_file)
                        task_image = Image()
                        task_image.create(self.image.id, is_task_image=True, name=config["name"]
                                                                           , author=config["author"]
                                                                           , version=config["version"])
                        task_image.load_task_config(config_file)
                # self.stop() 
                self._deconfigure()
                self._umount()

        else:
            raise Exception("Container doesn't exist")

                



def main():
    try:
        if len(sys.argv) == 1:
            Image.list()

        elif len(sys.argv) == 2:
            image: Image
            if sys.argv[1] == "new":
                image = Image()
                image.create()
                print(image.id)
            else:
                raise Exception("Incorrect command")

        elif sys.argv[1] == "delete" or sys.argv[1] == "del" or sys.argv[1] == "remove" or sys.argv[1] == "rm":
            for image_id in sys.argv[2::]:
                try:
                    image = Image(image_id)
                    image.delete()
                    print(' '.join(["Image", image_id, "has been deleted successfully"]))

                except Exception as e:
                    print(e)

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

                elif sys.argv[1] == "create":
                    image = Image(sys.argv[2])
                    container = Container(image)
                    container.start(mode=Container.Mode.task_create)

                else:
                    raise Exception("Unknown argument")

        else:
            raise Exception("Incorrect command")
    except Exception as e:
        print(e)


if __name__ == "__main__":
    # Проверка, запущена ли программа с правами суперпользователя
    if os.geteuid() != 0:
        print("Эта программа должна быть запущена с правами суперпользователя. Используйте 'sudo'.")
        sys.exit(1)  # Завершение программы с кодом 1 (ошибка)
    
    main()
