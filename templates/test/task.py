import os
import toml
import glob

from stage import Stage
from syshelp import remove, copy


class Task():
    class Config():
        config_filename = "task_settings.toml"
        stage_config_filename = "stage_settings.toml"


    def __init__(self, config_dir: str):
        os.makedirs(config_dir, exist_ok=True)
        for file_path in glob.glob(os.path.join(config_dir, '*.toml')):
            if "settings" not in file_path:
                remove(file_path)

        self.config_dir = config_dir
        self.config_file = os.path.join(config_dir, Task.Config.config_filename)
        self.stage_config_file = os.path.join(config_dir, Task.Config.stage_config_filename)
        self._curstage = None
        self._stagenum = 0


    def start_stage(self):
        if self._curstage is None:
            scf: str
            if os.path.isfile(self.stage_config_file):
                scf = self.stage_config_file

            elif os.path.isfile(self.config_file):
                scf = self.config_file

            else:
                raise Exception("Config file for task not founded")

                
            self._curstage = Stage(os.path.join(self.config_dir, 'stage' + str(self._stagenum) + '.toml'), scf)
            remove(self.stage_config_file)

            self._curstage.start()

        else:
            raise Exception('Stage has already started')


    def stop_stage(self):
        if self._curstage is not None:
            self._curstage.stop()
            self._curstage.save()
            self._curstage = None
            self._stagenum += 1
            # self.config[''.join(['stage', str(self._stagenum)])] = self._curstage.config

        else:
            raise Exception("Stage has not been started")


    def dump_settings(self, dest):
        copy(self.config_file, dest)


    def __del__(self):
        if self._curstage:
            self.stop_stage()
            raise Exception('Running stage has been stopped with DVS delete, most likely config has not been saved')
