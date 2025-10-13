import toml
import os

from hashpass.settings import Settings

settings = Settings()


class UserConfig:
    _config: dict

    username: str
    task_progress: dict

    def __init__(self):
        path = settings.userconfig_path
        try:

            if not os.path.isfile(path):
                dirpath = os.path.dirname(os.path.abspath(path))
                os.makedirs(dirpath, exist_ok=True)
                self._config = {"username": "", "task_progress": {}}
            else:
                self._config = toml.load(path)

            self._config.setdefault("username", "")
            self._config.setdefault("task_progress", {})
            self.username = self._config["username"]
            self.task_progress = self._config["task_progress"]


        except Exception as e:
            raise Exception(": ".join([f"User config file {path} - damaged, please fix it", str(e)]))


    def get_key(self, task_number: int) -> str:
        if str(task_number) in self.task_progress:
            return self.task_progress[str(task_number)]

        return ""

            
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
            raise Exception(": ".join([f"User config file {settings.userconfig_path} - damaged, please fix it", e]))




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

            with open(settings.userconfig_path, "w") as ucf:
                toml.dump(self._config, ucf)

        except Exception as e:
            raise Exception(" ".join(["Can't modify user config and save to", settings.userconfig_path, e]))



