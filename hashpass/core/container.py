import os
import uuid
import subprocess
import toml
import time

from threading import Thread

from hashpass.core.image import Image

from hashpass.settings import Settings
from hashpass.userconfig import UserConfig

from hashpass.utils import remove
from hashpass.key import calc_key


settings = Settings()


class Container:
    class Config:
        config_dir = settings.container_config_dir
        templates_dir = settings.templates_dir
        config_filename = settings.container_config_filename
        task_config_filename = settings.task_config_filename
        config_imagelink_dirname = settings.container_config_imagelink_dirname

    class Mode:
        edit = "Editing image environment for tasks"
        task_play = "Completing a task"
        task_create = "Creating a task"

    class Status:
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
        self._task_statusfile = os.path.join(self._task_workdir, settings.task_status_filename)
        self._task_hooks_dir = os.path.join(self._task_workdir, settings.task_hooks_dirname)

        self.save()

        self.status = Container.Status.created

    def __del__(self):
        pass
        # remove(self.config_dir)

    def save(self, exists_ok=False):
        if os.path.isdir(self.config_dir):
            if not exists_ok:
                raise Exception("Config dir already exist, rm this and try again")
        else:
            os.makedirs(self.config_dir)

        data = dict()
        data["container"] = dict()
        data["container"]["id"] = self.id
        data["container"]["image"] = self.image.get_id()

        with open(os.path.join(self.config_dir, Container.Config.config_filename), "w") as f:
            toml.dump(data, f)

    def _mount(self, mode: Mode):
        self._workdir = os.path.join(self.config_dir, "work")
        for dir in [self._workdir, self.mountpoint]:
            os.makedirs(dir, exist_ok=True)

        self._lowerdirs = list()
        self._layers = self.image.get_layers()

        self._layers.append(Image.Config.config_layer_basesettings)
        self._layers.append(self.image.get_id())
        self._layers.append(Image.Config.config_layer_base)
        if mode == Container.Mode.task_play:
            self._layers.append(Image.Config.config_layer_taskchecker)
        else:
            self._layers.append(Image.Config.config_layer_taskcreator)


        imagelink_path = os.path.join(self.config_dir, Container.Config.config_imagelink_dirname)
        os.makedirs(imagelink_path, exist_ok=True)
        for num, layer in enumerate(self._layers):
            layer_path = os.path.join(Image.Config.config_dir, Image(layer).get_id())
            os.symlink(layer_path, os.path.join(imagelink_path, str(num)), target_is_directory=True)
            self._lowerdirs.append(os.path.join(Container.Config.config_imagelink_dirname, str(num)))

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
                                      ,"upperdir=" + self._upperdir, "workdir=" + self._workdir]),
                                self.mountpoint], check=True, cwd=self.config_dir)

        with open(self._task_statusfile, "w") as f:
            f.write("created\n")

        if mode == Container.Mode.task_play:
            userconfig = UserConfig()
            k = calc_key(settings.masterkey, userconfig.username, Image._to_fullname(self.image.author,
                                                                                     self.image.name,
                                                                                     self.image.version))

            for d in ['etc', 'home', 'root', '.hash/dvs', 'opt']:
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



    def _umount(self):
        remove(os.path.join(self.config_dir, Container.Config.config_imagelink_dirname))
        subprocess.run(["umount", self.mountpoint], check=True)


    def _start(self):
        subprocess.run(["systemd-nspawn", "-b", "-q"
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
                if self.image.get_type() != Image.Type.task:
                    raise Exception(' '.join(["Image with id =", self.image.get_id(), "is not task image"]))

                image_is_empty = False

            elif mode == Container.Mode.edit:
                image_is_empty = False

            while True:
                try:
                    self._mount(mode)

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
                            self.image.set_type(Image.Type.task)
                            self.image.load_task_config(config_file)
                            self.image.save()

                            image_is_empty = False


                    self.stop() 
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

