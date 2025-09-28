#!/bin/env python3

import sys
import os
import uuid
import subprocess
import toml
import glob
import time
import shutil
import requests
import tarfile
import json

from threading import Thread
from tabulate import tabulate

from syshelp import copy,remove,move,read
from key import calc_key
from settings import Settings
from userconfig import UserConfig


settings = Settings()
userconfig = UserConfig()


class Image():
    class Config():
        config_dir = settings.image_config_dir
        config_filename = settings.image_config_filename
        task_work_dirname = settings.task_work_dirname
        task_config_dirname = settings.task_config_dirname
        task_config_filename = settings.task_config_filename
        task_hooks_dirname = settings.task_hooks_dirname

    class Type():
        simple = "simple"
        task = "task"
        base = "base"
    

    def __init__(self, param=None):
        os.makedirs(Image.Config.config_dir, exist_ok=True)

        self.id : str
        self.name : str
        self.author : str
        self.fullname: str
        self.version : str
        self.layers = list()
        self.type: str
        
        image: list
        if param is not None:
            image = Image.get(param)
            if not image:
                raise Exception(' '.join(["Can't find image", param, "locally"]))

            self.id = image['image']['id']
            self.name = image['image']['name']
            self.author = image['image']['author']
            self.version = image['image']['version']
            self.fullname = Image._to_fullname(self.author, self.name, self.version)
            self.layers = image['image']['layers']
            self.type = image['image']['type']

            self.config_dir = os.path.join(Image.Config.config_dir, self.id)


    def edit(self):
        container = Container(self)
        container.start(mode=Container.Mode.edit)


    def import_from_fs(self, path: str): 
        # функция отвечает за копирование файловой системы в образ path - путь до каталога, после которого начинается файловая система
        if os.path.isdir(path):
            copy(path, self.config_dir)
        else:
            raise Exception("Import path doesn't exist or isn't dir")

    
    def create(self, param=None): #FIXME create must create new image and return them
        if param is None:
            # FIXME update tree with exists image
            self.type = Image.Type.base

        else:
            parent_image = Image.get(param)
            if parent_image:
                self.type = Image.Type.simple
                self.layers = parent_image['image']['layers']
                self.layers.append(parent_image['image']['id'])

            else:
                raise Exception(f"Can't find image {param}")

        
        self.name = read("Enter name of image: ").strip()
        self.author = read("Enter author of image: ").strip()
        self.version = read("Enter version of image: ", default="latest").strip()

        self.fullname = Image._to_fullname(self.author, self.name, self.version)
        if Image.get(self.fullname):
            raise Exception(f"{self.fullname} already exist")

        self.id = str(uuid.uuid4()).replace("-", "")
        self.config_dir = os.path.join(Image.Config.config_dir, self.id)
        self.save()

        return self.id


    def delete(self):
        print(f"Deleting {self.fullname}")

        for image in Image.list():
            if self.id in image.layers:
                image.delete()

        if os.path.exists(self.config_dir):
            remove(self.config_dir)

        print(f"✅ Delete {self.fullname} successfull")


    def info(self) -> dict:
        data = dict()
        config_path = os.path.join(self.config_dir, Image.Config.config_filename)
        if os.path.isfile(config_path):
            data = toml.load(config_path)

        else:
            data["image"] = dict()


        data["image"]["name"] = self.name
        data["image"]["author"] = self.author
        data["image"]["version"] = self.version
        data["image"]["id"] = self.id
        data["image"]["type"] = self.type
        data["image"]["layers"] = self.layers

        return data


    def save(self, is_base_image=False):
        data = self.info()
        with open(Image.Config.config_filename, "w") as f:
            toml.dump(data, f)

        if is_base_image:
            copy(os.getcwd(), self.config_dir, progress_bar=True)

        else:
            move(Image.Config.config_filename, self.config_dir + '/')


    def _parse_fullname(fullname: str) -> list: # return [author, name, version]
        try:
            author, name = fullname.split('/')

            if ':' in name:
                name, version = name.split(':')

            else:
                version = 'latest'

            return [author, name, version]

        except Exception():
            raise Exception("Image name incorrect")


    def _to_fullname(*args) -> str:
        if len(args) == 1 and type(args[0]) == dict:
            data = args[0]
            if data.get("image") and data["image"].get("name") \
                and data["image"].get("author") and data["image"].get("version"):
                return data["image"]["author"] + '/' + data["image"]["name"] + ':' + data["image"]["version"]


        elif len(args) == 1 and type(args[0]) == str:
            if ':' in args[0]:
                return args[0]
                
            else:
                return args[0] + ':latest'

        elif len(args) == 3:
            return args[0] + '/' + args[1] + ':' + args[2]

        elif len(args) == 2:
            return args[0] + '/' + args[1] + ':' + 'latest'



        raise Exception("Image incorrect")


    def get(param) -> dict: # return fullname
        if isinstance(param, str):
            if '/' in param:
                author, name, version = Image._parse_fullname(param)
                for file in glob.glob(Image.Config.config_dir + "/**/" + Image.Config.config_filename, recursive=False):
                    temp = toml.load(file)
                    if temp['image']['name'] == name and temp['image']['version'] == version and temp['image']['author'] == author:
                        return temp

            else:
                id = param
                for file in glob.glob(Image.Config.config_dir + "/**/" + Image.Config.config_filename, recursive=False):
                    temp = toml.load(file)

                    if temp['image']['id'] == id:
                        return temp

        return None


    def get_fullname(param) -> str: # return fullname
        manifest = Image.get(param)
        if manifest:
            return Image._to_fullname(manifest['image']['author'], manifest['image']['name'], manifest['image']['name'])

        return None


    def list() -> list: # return [manifest, manifest, ...]
        images = list()
        for file in glob.glob(Image.Config.config_dir + "/**/" + Image.Config.config_filename, recursive=False):
            manifest = toml.load(file)
            if manifest:
                images.append(Image(manifest['image']['id']))

        return images


    def print_list():
        table = [["ID", "NAME", "TYPE", "PARENT IMAGE"]]

        for file in glob.glob(Image.Config.config_dir + "/**/" + Image.Config.config_filename, recursive=False):
            temp = toml.load(file)

            parent_image_fullname = None
            if temp["image"]["layers"]:
                parent_image_fullname = Image.get_fullname(temp["image"]["layers"][-1])

            table.append([temp["image"]["id"]
                          , Image._to_fullname(temp["image"]["author"], temp["image"]["name"], temp["image"]["version"])
                          , temp["image"]["type"], parent_image_fullname])

        print(tabulate(table, headers="firstrow", tablefmt="grid"))


    def load_task_config(self, path: str):
        if self.type == Image.Type.task:
            _ = toml.load(path) # test toml via load
            copy(path, os.path.join(self.config_dir, Image.Config.task_config_dirname, Image.Config.task_config_filename))

        else:
            raise Exception(' '.join(["Image id =", self.id, "is not task image"]))


    def load_task_hooks(self, path: str):
        copy(path, os.path.join(self.config_dir, Image.Config.task_work_dirname, Image.Config.task_hooks_dirname))




class Container():
    class Config():
        config_dir = settings.container_config_dir
        templates_dir = settings.templates_dir
        config_filename = settings.container_config_filename
        task_config_filename = settings.task_config_filename


    class Mode():
        edit = "Editing image environment for tasks"
        task_play = "Completing a task"
        task_create = "Creating a task"

    class Status():
        created = "Container with task has been created, but not started"
        started = "Container with task has been started"
        stopping = "Container stopping"
        restarting = "Container restarting"
        stopped = "Container with task has been stopped"
        deleted = "Container with task has been deleted or doesn't exist"
        image_updating = "Container fs changes will be saved to self image and restart"
        image_saving = "Container fs changes will be saved to self image and exit"
        task_playing = "Container fs changes will be saved to self image and play task"


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

            elif status_text == "restarting":
                return Container.Status.restarting

            elif status_text == "deleted":
                return Container.Status.deleted

            elif status_text == "task playing":
                return Container.Status.task_playing


            elif status_text == "image updating":
                return Container.Status.image_updating

            elif status_text == "image saving":
                return Container.Status.image_saving

            else:
                raise Exception("Can't read a some status from text or file")


    def __init__(self, image: Image):
        os.makedirs(Container.Config.config_dir, exist_ok=True)

        self.id = str(uuid.uuid4()).replace("-", "")
        self.image = image

        self.config_dir = os.path.join(Container.Config.config_dir, self.id)
        self.mountpoint = os.path.join(self.config_dir, settings.container_mountpoint_dirname)
        
        self._upperdir = None
        self._lowerdir = None
        self._workdir = None
        self._lowerdirs = list()

        self._task_workdir = os.path.join(self.mountpoint, settings.task_work_dirname)
        self._task_config_dir = os.path.join(self.mountpoint, settings.task_config_dirname)
        self._task_logfile = os.path.join(self._task_workdir, settings.task_log_filename)
        self._task_cmdfile = os.path.join(self._task_workdir, settings.task_cmd_filename)
        self._task_cmdoutfile = os.path.join(self._task_workdir, settings.task_cmdout_filename)
        self._task_tmpfile = os.path.join(self._task_workdir, settings.task_tmp_filename)
        self._task_pwdfile = os.path.join(self._task_workdir, settings.task_pwd_filename)
        self._task_bindir = os.path.join(self._task_workdir, settings.task_bin_dirname)
        self._task_signal_string = settings.task_signal_string
        self._task_statusfile = os.path.join(self._task_workdir, settings.task_status_filename)
        self._task_hooks_dir = os.path.join(self._task_workdir, settings.task_hooks_dirname)

        self.save()

        self.status = Container.Status.created


    def __del__(self):
        remove(self.config_dir)


    def save(self, exists_ok=False):
        if os.path.isdir(self.config_dir):
            if not exists_ok:
                raise Exception("Config dir already exist, rm this and try again")
        else:
            os.makedirs(self.config_dir)

        data = dict()
        data["container"] = dict()
        data["container"]["id"] = self.id
        data["container"]["image"] = self.image.id

        with open(os.path.join(self.config_dir, Container.Config.config_filename), "w") as f:
            toml.dump(data, f)


    def _configure(self, mode: Mode):
        os.makedirs(self._task_workdir, exist_ok=True)
        with open(self._task_logfile, "a") as f:
            pass # make file 
        with open(self._task_cmdfile, "a") as f:
            pass # make file 
        with open(self._task_cmdoutfile, "a") as f:
            pass # make file 
        with open(self._task_tmpfile, "a") as f:
            pass # make file 
        with open(self._task_pwdfile, "a") as f:
            pass # make file 
        with open(self._task_statusfile, "w") as f:
            f.write("created\n")

        os.chmod(self._task_workdir, 0o755)
        os.chmod(self._task_logfile, 0o666)
        os.chmod(self._task_cmdfile, 0o666)
        os.chmod(self._task_cmdoutfile, 0o666)
        os.chmod(self._task_tmpfile, 0o666)
        os.chmod(self._task_pwdfile, 0o666)
        os.chmod(self._task_statusfile, 0o666)

        copy(os.path.join(Container.Config.templates_dir, "dvs", "task.sh"), os.path.join(self.mountpoint, "usr", "bin", "task"))
        os.chmod(os.path.join(self.mountpoint, "usr", "bin", "task"), 0o555)

        # copy(self._task_bindir, os.path.join(self.mountpoint, "tmp/"))
        copy(os.path.join(Container.Config.templates_dir, "dvs"), self._task_bindir, with_replace=False)
        # move(os.path.join(self.mountpoint, "tmp/bin"), self._task_bindir)

        # subprocess.run(["pyarmor", "gen", "-r", self._task_bindir, "-O", os.path.join(self.mountpoint, "tmp/dist")], check=True)
        

        if mode == Container.Mode.task_create or mode == Container.Mode.edit:
            copy(os.path.join(Container.Config.templates_dir, "dvs", "image.sh"), os.path.join(self.mountpoint, "usr", "bin", "image"))
            os.chmod(os.path.join(self.mountpoint, "usr", "bin", "image"), 0o555)

            copy(os.path.join(Container.Config.templates_dir, "dvs", "action.sh"), os.path.join(self.mountpoint, "usr", "bin", "action"))
            os.chmod(os.path.join(self.mountpoint, "usr", "bin", "action"), 0o555)

            copy(os.path.join(Container.Config.templates_dir, "dvs", "taskcreator.service"), os.path.join(self.mountpoint, "etc", "systemd", "system", "taskcreator.service"))
            if not os.path.islink(os.path.join(self.mountpoint, "etc", "systemd", "system", "multi-user.target.wants", "taskcreator.service")):
                remove(os.path.join(self.mountpoint, "etc", "systemd", "system", "multi-user.target.wants", "taskcreator.service"))
                os.symlink(os.path.join("/", "etc", "systemd", "system", "taskcreator.service"), os.path.join(self.mountpoint, "etc", "systemd", "system", "multi-user.target.wants", "taskcreator.service")) # magic

            copy(os.path.join(Container.Config.templates_dir, "dvs", "task_settings.toml"), os.path.join(self._task_workdir, "config", "task_settings.toml"))
            os.chmod(os.path.join(self._task_workdir, "config", "task_settings.toml"), 0o666)
            os.chmod(os.path.join(self._task_workdir, "config"), 0o777)

            os.chmod(os.path.join(self.mountpoint, settings.task_config_dirname), 0o777)


        elif mode == Container.Mode.task_play:
            copy(os.path.join(Container.Config.templates_dir, "dvs", "taskchecker.service"), os.path.join(self.mountpoint, "etc", "systemd", "system", "taskchecker.service"))

            if not os.path.islink(os.path.join(self.mountpoint, "etc", "systemd", "system", "multi-user.target.wants", "taskchecker.service")):
                remove(os.path.join(self.mountpoint, "etc", "systemd", "system", "multi-user.target.wants", "taskchecker.service"))
                os.symlink(os.path.join("/", "etc", "systemd", "system", "taskchecker.service"), os.path.join(self.mountpoint, "etc", "systemd", "system", "multi-user.target.wants", "taskchecker.service"))

            k = calc_key(settings.masterkey, userconfig.username, Image._to_fullname(self.image.author, 
                                                                                self.image.name, 
                                                                                self.image.version))

            for d in ['etc', 'home', 'root', '.hash/bin']:
                try:
                    # Используем grep для быстрого поиска файлов с key{}
                    result = subprocess.run(['grep', '-rl', 'key{}', os.path.join(self.mountpoint, d)], 
                                          capture_output=True, text=True)
                    files = result.stdout.splitlines()
                    
                    # Заменяем только в найденных файлах
                    for file in files:
                        try:
                            subprocess.run(['sed', '-i', 's/key{}/' + k + '/g', file], 
                                         check=False)
                        except:
                            continue
                except:
                    continue


        copy(os.path.join(Container.Config.templates_dir, "dvs", "hash.sh")
                      , os.path.join(self.mountpoint, "usr", "bin", "hash"))
        os.chmod(os.path.join(self.mountpoint, "usr", "bin", "hash"), 0o555)

        if mode == Container.Mode.task_create or mode == Container.Mode.edit:
            copy(os.path.join(Container.Config.templates_dir, "dvs", "stage.sh")
                  , os.path.join(self.mountpoint, "usr", "bin", "stage"))
            os.chmod(os.path.join(self.mountpoint, "usr", "bin", "stage"), 0o555)


        with open(os.path.join(self.mountpoint, "etc", "bash.bashrc"), "a+") as f:
            f.seek(0)
            for line in reversed(f.readlines()):
                if line.strip() != "/usr/bin/hash":
                    continue
                break

            else:
                conf_lines = list()

                conf_lines.append("alias bash=\"/usr/bin/hash\"")
                # conf_lines.append("alias alert='notify-send --urgency=low -i \"$([ $? = 0 ] && echo terminal || echo error)\" \"$(history|tail -n1|sed -e '\\''s/^\s*[0-9]\+\s*//;s/[;&|]\s*alert$//'\\'')\"'")
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
                    f.write(line + " # " + self._task_signal_string + "\n")


    def _deconfigure(self):
        remove(self._task_cmdfile)
        remove(self._task_logfile)
        remove(self._task_cmdoutfile)
        remove(self._task_tmpfile)
        remove(self._task_statusfile)
        remove(self._task_pwdfile)

        remove(self._task_bindir)
        remove(os.path.join(self.mountpoint, "usr", "bin", "hash"))
        remove(os.path.join(self.mountpoint, "usr", "bin", "task"))
        remove(os.path.join(self.mountpoint, "usr", "bin", "stage"))
        remove(os.path.join(self.mountpoint, "usr", "bin", "image"))
        remove(os.path.join(self.mountpoint, "usr", "bin", "action"))
        remove(os.path.join(self.mountpoint, "etc", "systemd", "system", "multi-user.target.wants", "taskcreator.service"))
        remove(os.path.join(self.mountpoint, "etc", "systemd", "system", "multi-user.target.wants", "taskchecker.service"))
        remove(os.path.join(self.mountpoint, "etc", "systemd", "system", "taskcreator.service"))
        remove(os.path.join(self.mountpoint, "etc", "systemd", "system", "taskchecker.service"))

        try:
            os.chmod(self._task_config_dir, 0o700)
            os.chmod(os.path.join(self._task_config_dir, Container.Config.task_config_filename), 0o700)
        except:
            pass

        deconf_lines: list
        with open(os.path.join(self.mountpoint, "etc", "bash.bashrc"), "r") as f:
            f.seek(0)
            lines = f.readlines()
            deconf_lines = [line for line in lines if self._task_signal_string not in line]

        with open(os.path.join(self.mountpoint, "etc", "bash.bashrc"), 'w') as f:
            f.writelines(deconf_lines)

        for f in glob.glob(os.path.join(self.mountpoint, "home", "**", ".hash"), recursive=False, include_hidden=True):
            remove(f)

        remove(os.path.join(self.mountpoint, "root", ".hash"))


    def _mount(self, mode: Mode):
        self._workdir = os.path.join(self.config_dir, "work")
        for dir in [self._workdir, self.mountpoint]:
            os.makedirs(dir, exist_ok=True)

        self._lowerdirs = list()
        for layer in self.image.layers:
            self._lowerdirs.append(os.path.join(Image.Config.config_dir, layer))

        self._lowerdirs.append(self.image.config_dir)
        self._upperdir = os.path.join(self.config_dir, "emptyupper")
        remove(self._upperdir)
        os.makedirs(self._upperdir, exist_ok=True)

        if not self._lowerdirs:
            self._lowerdir = os.path.join(self.config_dir, "emptylower")
            os.makedirs(self._lowerdir, exist_ok=True)

        else:
            self._lowerdir = ':'.join(self._lowerdirs[::-1])


        subprocess.run([ "mount", "overlay", "-t", "overlay", 
                                  "-o", ','.join(["lowerdir=" + self._lowerdir
                                      , "upperdir=" + self._upperdir , "workdir=" + self._workdir]),
                                self.mountpoint], check=True)


    def _umount(self):
        subprocess.run([ "umount", self.mountpoint], check=True)


    def _start(self):
        subprocess.run([ "systemd-nspawn", "-b", "-q"
                                                 , "-M", self.id
                                                 , "--user", "root"
                                                 , "-D", self.mountpoint], check=True) # True or False #FIXME


    def get_status(self):
        if os.path.exists(self._task_statusfile):
            return Container.Status.get_from(self._task_statusfile)

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
            try:
                self.status = self.get_status()

            except Exception:
                time.sleep(5)
                self.status = self.get_status()

            if self.status == Container.Status.stopped or self.status == Container.Status.deleted:
                return

            elif self.status == Container.Status.created or self.status == Container.Status.started:
                continue

            else:
                self.stop()
                return #FIXME add restarted and another status



    def start(self, mode=Mode.task_play):
        if self.id:
            self.mode = mode
            image_is_empty = True

            if mode == Container.Mode.task_play:
                if self.image.type != Image.Type.task:
                    raise Exception(' '.join(["Image with id =", self.image.id, "is not task image"]))

                image_is_empty = False

            elif mode == Container.Mode.edit:
                image_is_empty = False

            while True:
                try:
                    self._mount(mode)
                    self._configure(mode)

                    thr = Thread(target=self._monitoring)
                    thr.start()
                    # proc = Process(target=self._monitoring)
                    # proc.start()

                    self._start()

                except:
                    raise

                finally:
                    if mode == Container.Mode.task_create or mode == Container.Mode.edit:
                        config_file = os.path.join(self._task_config_dir, Container.Config.task_config_filename)
                        if os.path.isfile(config_file):
                            self.image.type = Image.Type.task
                            self.image.load_task_config(config_file)
                            self.image.save()

                            image_is_empty = False


                    self.stop() 

                    if self.status == Container.Status.image_saving or self.status == Container.Status.image_updating or self.status == Container.Status.task_playing:
                        self.image.load_task_hooks(self._task_hooks_dir)

                    self._deconfigure()

                    self._umount()

                if self.status == Container.Status.task_playing:
                    mode = Container.Mode.task_play
                    continue

                if self.status == Container.Status.restarting:
                    continue

                elif self.status == Container.Status.image_updating:
                    self.image.import_from_fs(self._upperdir)
                    image_is_empty = False
                    continue

                elif self.status == Container.Status.image_saving:
                    self.image.import_from_fs(self._upperdir)
                    image_is_empty = False


                if image_is_empty:
                    print("❌ Deleting empty image")
                    self.image.delete()

                elif mode != Container.Mode.task_play:
                    if mode == Container.Mode.edit:
                        print(f"✅ Edit {self.image.fullname} successfull")

                    else:
                        print(f"✅ Create {self.image.fullname} successfull")

                break

        else:
            raise Exception("Container doesn't exist")


def get_info(server_url: str, param: str):
    data = {'param': param}
    response = requests.post(f"{server_url}/info", data=data)
    if response.status_code != 200:
        raise Exception(f"{param} not found on registry")

    return response.json()


def download(server_url: str, image_id: str):
    if Image.get(image_id):
        return

    print(f"Pulling image: {image_id}")

    archive_response = requests.get(f"{server_url}/download/{image_id}", stream=True)
    if archive_response.status_code != 200:
        raise Exception(f"Download image error: {archive_response.text}")

    config_dir = os.path.join(Image.Config.config_dir, image_id)
    os.makedirs(config_dir, exist_ok=True)
    archive_path = os.path.join(config_dir, f"{image_id}.tar.gz")

    with open(archive_path, "wb") as f:
        f.write(archive_response.content)

    with tarfile.open(archive_path, "r:gz", format=tarfile.PAX_FORMAT) as tar:
        tar.extractall(path=config_dir, filter="fully_trusted")

    remove(archive_path)
    print(f"✅ Pull {image_id} successfull")
                

def pull(server_url: str, param = None):
    if not param:
        raise Exception(f"Image with name {param} can't be exist")

    if Image.get(param):
        print(f"{param} already pulled")
        return

    manifest = get_info(server_url, param)

    thrs = list()
    for layer_image_id in manifest["image"]["layers"]:
        thr = Thread(target=download, args=(server_url, layer_image_id))
        thr.start()
        thrs.append(thr)

    thr = Thread(target=download, args=(server_url, manifest["image"]["id"]))
    thr.start()
    thrs.append(thr)

    for thr in thrs:
        thr.join()



def get_remote_images(server_url: str):
    """Получение списка всех образов"""
    response = requests.get(f"{server_url}/images")
    if response.status_code != 200:
        raise Exception(f"Ошибка: {response.text}")

    images = response.json()

    print("Список образов в registry:")
    table = [["ID", "NAME", "TYPE", "PARENT IMAGE ID"]]
    for img in images:
        parent_image_id = None
        if img["image"]["layers"]:
            parent_image_id = img["image"]["layers"][-1]

        table.append([img["image"]["id"]
                      , Image._to_fullname(img["image"]["author"], img["image"]["name"], img["image"]["version"])
                      , img["image"]["type"], parent_image_id])

    print(tabulate(table, headers="firstrow", tablefmt="grid"))
 



def main():
    try:
        server_url = settings.server_url
        if len(sys.argv) == 1:
            Image.print_list()

        elif len(sys.argv) == 2:
            image: Image
            if sys.argv[1] == "new":
                image = Image()
                image.create()
                image.import_from_fs(os.getcwd())
                print(image.id)

            elif sys.argv[1] == "pull":
                get_remote_images(server_url)

            else:
                raise Exception("Incorrect command")

        elif sys.argv[1] == "delete" or sys.argv[1] == "del" or sys.argv[1] == "remove" or sys.argv[1] == "rm":
            ans = input("This command delete all dependecies image, you are sure? [y] ")
            if 'y' != ans.strip().lower():
                return

            for image_id in sys.argv[2::]:
                try:
                    image = Image(image_id)
                    image.delete()

                except Exception as e:
                    print(' '.join(['❌' , str(e)]))

        # elif sys.argv[1] == "rename": change to tag
        #     if len(sys.argv) != 4:
        #         raise Exception("Incorrect args")

        #     try:
        #         _ = Image(sys.argv[3])

        #     except Exception:
        #         image = Image(sys.argv[2])

        #         new_image_id = str(uuid.uuid4()).replace("-", "")
        #         move(os.path.join(Image.Config.config_dir, image.id), os.path.join(Image.Config.config_dir, new_image_id))

        #         image.author, image.name, image.version = Image._parse_fullname(sys.argv[3])
        #         image.id = new_image_id
        #         image.save()

        #         print(f"Rename {sys.argv[2]} to {sys.argv[3]} successfull")

        #     else:
        #         raise Exception(f"Image {sys.argv[3]} already exist")


        elif len(sys.argv) == 3:
                if sys.argv[1] == "new":
                    image = Image()
                    image.create(sys.argv[2])
                    image.edit()

                elif sys.argv[1] == "edit":
                    image = Image(sys.argv[2])
                    image.edit()

                elif sys.argv[1] == "start" or sys.argv[1] == "play":
                    try:
                        image = Image(sys.argv[2])

                    except Exception as e:
                        pull(server_url, sys.argv[2])
                        image = Image(sys.argv[2])
                        
                    container = Container(image)
                    container.start(mode=Container.Mode.task_play)

                elif sys.argv[1] == "create":
                    image = Image()
                    image.create(sys.argv[2])

                    container = Container(image)
                    container.start(mode=Container.Mode.task_create)

                elif sys.argv[1] == "pull":
                    pull(server_url, sys.argv[2])


        else:
            raise Exception("Incorrect command")

    except Exception as e:
        print(' '.join(['❌' , str(e)]))


if __name__ == "__main__":
    # Проверка, запущена ли программа с правами суперпользователя
    if os.geteuid() != 0:
        print("Эта программа должна быть запущена с правами суперпользователя. Используйте 'sudo'.")
        sys.exit(1)  # Завершение программы с кодом 1 (ошибка)
    
    main()

