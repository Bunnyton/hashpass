from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    masterkey: str = '10383f373f292407117439070130373440255468657365206172652'
    server_url: str = "http://185.212.148.108:8000"

    config_dir: str = "/opt/.hashpass/config"

    image_config_dir: str = os.path.join(config_dir, 'images')
    image_config_filename: str = "manifest.toml"
    image_task_config_dirname: str = ".hash/.task"
    image_task_config_filename: str = "config.toml"
    image_task_hooks_dirname: str = ".hash/bin/hooks"

    task_config_dirname = ".hash"
    task_log_filename = ".hash.log"
    task_cmd_filename = ".hash.cmd"
    task_cmd_outfilename = ".hash.cmd.out"
    task_tmp_filename = ".hash.tmp"
    task_pwd_filename = ".hash.pwd"
    task_bin_dirname = "bin"
    task_signal_string = "hash"
    task_status_filename =".hash.status"

    self._task_config_dir = os.path.join(self._hash_config_dir, ".task")
    self._task_hooks_dir = os.path.join(self._hash_config_dir, "bin", "hooks")


    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        fields = { 'masterkey': {'env': None}}


class UserSettings():

    username: str

    def __init__(self):
        try:
            settings = Settings()
            username = toml.load("/opt/.hashpass/config/userconfig.toml")["username"]

        except Exception:
            raise Exception("Username ")



settings = Settings()

# Использование
print(settings.api_key)
