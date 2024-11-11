import socket
import os
import glob

import toml
from simhash import Simhash


def log(msg: str, clientsocket: socket.socket):
    print(msg.replace('\0', ''))
    clientsocket.send(bytes(msg, 'utf-8'))

class TaskCheckerServer():
    config = None
    stage_num = 0

    host = '127.0.0.1'
    port = 17171
    max_buff_size = 4096
    sock = None

    def __init__(self, config_file="config.toml"):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((self.host, self.port))

        with open(config_file, 'r') as cf:
            self.config = toml.load(cf)


    def task_complete(self):
        return 'key'


    def check_path(self, path) -> bool:
        stage_config = self.config[''.join(['stage', str(self.stage_num)])]
        if stage_config['changes'][path]['state'] == 'modified' or stage_config['changes'][path]['state'] == 'created':
            if stage_config['changes'][path]['is_dir']:
                if os.path.exists(path) and os.path.isdir(path):
                    return True

            elif os.path.exists(path) and os.path.isfile(path):
                if Simhash(path, from_file=True).distance(Simhash(stage_config['changes'][path]['hash'], from_hash=True)) < stage_config['options']['fs_accuracy']:
                    return True

        else:
            if not os.path.exists(path):
                return True

        return False


    def check_stage(self) -> bool:
        if self.stage_num < self.config['stage_amount']:
            stage_config = self.config[''.join(['stage', str(self.stage_num)])]
            for change in stage_config['changes']:
                if not self.check_path(change):
                    return False

        return True


    def check(self):
        if self.check_stage():
            self.stage_num += 1
            if self.stage_num >= self.config['stage_amount']:
                return self.task_complete()
        return None


    def _handle_cmd(self, clientsocket: socket.socket):
        buf = clientsocket.recv(self.max_buff_size)
        try:
            if not buf:
                return
            cmd = buf.decode().split()
            print(''.join(['Get: ', buf.decode()]))

            if len(cmd) == 1 and cmd[0] == 'check':
                res = self.check()
                if res is not None:
                    log(res + '\0', clientsocket)
                    exit()
                else:
                    log('\0', clientsocket)
            else:
                raise Exception('Invalid command')

        except Exception as e:
            raise
            # log(''.join(['Error: ', str(e), '\0']), clientsocket)

    def start(self):
        self.sock.listen(10)
        while True:
            # accept connections from outside
            (clientsocket, address) = self.sock.accept()

            self._handle_cmd(clientsocket)
            clientsocket.close()


server = TaskCheckerServer(config_file="./config/config.toml")
server.start()
