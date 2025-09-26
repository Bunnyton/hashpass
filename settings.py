from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional
import os

class Settings(BaseSettings):
    masterkey: str = Field(
        default = '10383f373f292407117439070130373440255468657365206172652',
        validation_alias = None
    )

    server_url: str = "http://127.0.0.1:8000"
    # server_url: str = "http://185.212.148.108:8000"

    app_dir: str = "/opt/.hashpass"
    sys_app_path: str = os.path.join(app_dir, "make_env.py")
    config_dir: str = os.path.join(app_dir, "config")
    templates_dir: str = os.path.join(app_dir, "templates")
    userconfig_path: str = os.path.join(config_dir, "userconfig.toml")

    image_config_dir: str = os.path.join(config_dir, 'images')
    image_config_filename: str = "manifest.toml"

    container_config_dir: str = os.path.join(config_dir, 'containers')
    container_config_filename: str = "manifest.toml"
    container_mountpoint_dirname: str = "mountpoint"

    task_work_dirname: str = ".hash"
    task_config_dirname: str = os.path.join(task_work_dirname, ".task")
    task_config_filename: str = "config.toml"
    task_hooks_dirname: str = "bin/hooks"

    task_log_filename: str = ".hash.log"
    task_cmd_filename: str = ".hash.cmd"
    task_cmdout_filename: str = ".hash.cmd.out"
    task_tmp_filename: str = ".hash.tmp"
    task_pwd_filename: str = ".hash.pwd"
    task_bin_dirname: str = "bin"
    task_signal_string: str = "hash"
    task_status_filename: str =".hash.status"

    tasks: dict = Field(
        # fullname: author/name:version
        default = { 
            '0': "bunnyton/hello:latest", 
            '1': "bunnyton/simple_ls:latest",
        },
        validation_alias = None
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


