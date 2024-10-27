import toml
from simhash import Simhash

class TaskChecker():
    config_file = str()
    stage_num = 0
    def __init__(self, config_file="/etc/hashpass/"):
        self.config_file = config_file


    def task_complete(self):
        print('key')

    def check_file(self, filename, stage_config) -> bool:
        hash = Simhash(filename).value()
    def check_stage(self, stage_config):
        for change_file in stage_config['changes']:
            if check_file(change_file, stage_config):
    def check(self):
        with open(self.config_file, 'r') as cf:
            config = toml.load(cf)
            check_stage(config[''.join('stage', str(self.stage_num))])
            if self.stage_num >= config['stage_amount']:
                task_complete()



