import toml
import os

from settings import Settings

settings = Settings()


class UserConfig():
    _config: dict

    username: str
    tasks: dict

    def __init__(self):
        path = settings.userconfig_path
        try:

            if not os.path.isfile(path):
                dirpath = os.path.dirname(os.path.abspath(path))
                os.makedirs(dirpath, exist_ok=True)
                self._config = {"username": "", "tasks": {}}
            else:
                self._config = toml.load(path)

            self._config.setdefault("username", "")
            self._config.setdefault("tasks", {})
            self.username = self._config["username"]
            self.tasks = self._config["tasks"]


        except Exception as e:
            raise Exception(': '.join([f"User config file {path} - damaged, please fix it", str(e)]))


    def get_key(self, task_number: int) -> str:
        if self.tasks.get(task_number):
            return self.tasks[task_number]

        return ""


    def get_last_task_num(self):
        try:
            nums = []
            for k in self.tasks.keys():
                nums.append(int(k))

            return max(nums) if nums else 0

        except Exception:
            e = "Task number must be int or str(int)"
            raise Exception(': '.join([f"User config file {path} - damaged, please fix it", e])) 


    def save(self, **kwargs):
        try:
            try:
                if kwargs.get("username"):
                    self._config["username"] = str(kwargs["username"])
                    self.username = self._config["username"]
            except:
                raise Exception("Username must be string")


            try:
                if kwargs.get("key") and kwargs.get("task_num"):
                    self.tasks[int(kwargs["task_num"])] = str(kwargs["key"])
            except:
                raise Exception("Format error: must be save(key: str, task_num: int)")

            with open(settings.userconfig_path, 'w') as ucf:
                toml.dump(self._config, ucf)

        except Exception as e:
            raise Exception(' '.join(["Can't modify user config and save to", settings.userconfig_path, e]))



