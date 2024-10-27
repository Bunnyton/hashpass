import os
import toml

from stage import Stage


class DVS():

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        _curstage = None
        _stagenum = 0

    def start_stage(self, mode=None, fs_analyzer=None, fs_accuracy=None, output_analyzer=None,
                    output_accuracy=None, observe_dirs=None):
        if self._curstage is None:
            self._curstage = Stage(''.join([self.config_dir, '/stage', str(self._stagenum), '.toml']), mode=mode,
                                   fs_analyzer=fs_analyzer,
                                   fs_accuracy=fs_accuracy,
                                   output_analyzer=output_analyzer, output_accuracy=output_accuracy,
                                   observe_dirs=observe_dirs)
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

    #  def save(self):
    #      if self._curstage is not None:
    #          self.stop_stage()
    #      with open(''.join([self.config_dir, 'stage', str(self._stagenum), '.toml']), 'w') as cf:
    #          toml.dump(self.config, cf)

    def __del__(self):
        if self._curstage is not None:
            self.stop_stage()
            raise Exception('Running stage has been stopped with DVS delete, most likely config has not been saved')
