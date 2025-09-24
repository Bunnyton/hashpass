from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    masterkey: str = '10383f373f292407117439070130373440255468657365206172652'
    server_url: str = "http://185.212.148.108:8000"

    app_dir = "/opt/.hashpass"
    config_dir: str = os.path.join(app_dir, "config")
    temlates_dir: str = os.path.join("templates")

    image_config_dir: str = os.path.join(config_dir, 'images')
    image_config_filename: str = "manifest.toml"

    container_config_dir: str = os.path.join(config_dir, 'containers')
    container_config_filename: str = "manifest.toml"


    task_work_dirname: str = ".hash"
    task_config_dirname: str = os.path.join(task_work_dirname, ".task")
    task_config_filename: str = "config.toml"
    task_hooks_dirname: str = os.path.join(task_work_dirname, "bin/hooks")

    task_log_filename: str = ".hash.log"
    task_cmd_filename: str = ".hash.cmd"
    task_cmd_outfilename: str = ".hash.cmd.out"
    task_tmp_filename: str = ".hash.tmp"
    task_pwd_filename: str = ".hash.pwd"
    task_bin_dirname: str = "bin"
    task_signal_string: str = "hash"
    task_status_filename: str =".hash.status"



    
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
