import toml
import os

from hashpass.settings import Settings

settings = Settings()


class UserConfig:
    _config: dict
    _path: str

    username: str
    task_progress: dict

    _new = True

    def __init__(self, username=None):
        try:
            if username:
                self._path = os.path.join(settings.userconfig_dir, username.replace(' ', '_') + ".toml")
                self._config = {"username": "", "task_progress": {}}
                os.makedirs(settings.userconfig_dir, exist_ok=True)
                if os.path.isfile(self._path):
                    self._config = toml.load(self._path)
                    self._new = False

                self._config["username"] = username
                self.username = self._config["username"]
                self._config.setdefault("task_progress", {})
                self.task_progress = self._config["task_progress"]

            elif os.path.isfile(settings.userconfig_tmp_file):
                self._config = toml.load(settings.userconfig_tmp_file)
                self.username = self._config["username"]
                self._path = os.path.join(settings.userconfig_dir, self.username.replace(' ', '_') + ".toml")
                self._new = False

                os.remove(settings.userconfig_tmp_file)

        except Exception as e:
            raise Exception(": ".join([f"User config file {self._path} - damaged, please fix it", str(e)]))


    def get_key(self, task_number: int) -> str:
        if str(task_number) in self.task_progress:
            return self.task_progress[str(task_number)]

        return ""


    def is_new(self):
        return self._new

            
    def get_task_name(self, task_num: int = None, all : bool = False) -> list:
        if task_num is None and all: 
            return settings.tasks.values()

        elif str(task_num) in settings.tasks:
            return settings.tasks[str(task_num)]

        else:
            raise Exception(f"Task with number {task_num} doesn't exist")



    def get_last_task_num(self) -> int | None:
        try:
            nums = []
            for k in self.task_progress.keys():
                nums.append(int(k))

            return max(nums) if nums else None

        except Exception:
            e = "Task number must be int or str(int)"
            raise Exception(": ".join([f"User config file {self._path} - damaged, please fix it", e]))




    def save(self, **kwargs) -> None:
        try:
            if "username" in kwargs:
                try:
                        self.username = str(kwargs["username"])

                except:
                    raise Exception("Username must be string")


            if "task_num" in kwargs and "key" in kwargs:
                try:
                    self.task_progress[str(int(kwargs["task_num"]))] = str(kwargs["key"])

                except:
                    raise Exception("Format error: must be save(key: str, task_num: int)")

            self._config["username"] = self.username
            self._config["task_progress"] = self.task_progress

            with open(self._path, "w", encoding="utf-8") as cf:
                toml.dump(self._config, cf)

        except Exception as e:
            raise Exception(" ".join(["Can't modify user config and save to", self._path, e]))


    def save_tmp(self):
        try:
            with open(settings.userconfig_tmp_file, "w", encoding="utf-8") as utf:
                toml.dump(self._config, utf)
        except Exception as e:
            raise Exception(" ".join(["Can't modify user tmp config and save to", settings.userconfig_tmp_file, e]))




