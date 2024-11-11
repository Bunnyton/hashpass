import socket
import os
import glob

import toml

from taskcreator import TaskCreator


def log(msg: str, clientsocket: socket.socket):
    print(msg.replace('\0', ''))
    clientsocket.send(bytes(msg, 'utf-8'))

class TaskCreatorServer:
    host = '127.0.0.1'
    port = 17170
    max_buff_size = 4096
    sock = None

    taskcreator = None
    config_dir = str()

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((self.host, self.port))

    def _handle_cmd(self, clientsocket: socket.socket):
        buf = clientsocket.recv(self.max_buff_size)
        try:
            if not buf:
                return
            cmd = buf.decode().strip()
            print(''.join(['Get: ', cmd]))

            if cmd.startswith('start'):  # start TaskCreator with config dir
                if self.taskcreator:
                    raise Exception('Task creating already started')

                self.config_dir = cmd.replace('start ', '')
                if not self.config_dir:
                    self.config_dir = "/.hash/.dvs"
                self.taskcreator = TaskCreator(self.config_dir)

                log('Task creating has been started\0', clientsocket)

            elif cmd == 'stop':
                if self.taskcreator:
                    del self.taskcreator
                    self.taskcreator = None
                    log('Task created successfully, please, verify config\0', clientsocket)

            elif cmd == 'save':
                if self.taskcreator:
                    del self.taskcreator
                    self.taskcreator = None

                config = dict()
                stage_amount = 0
                for filename in os.listdir(self.config_dir):
                    with open(os.path.join(self.config_dir, filename), 'r') as cf:
                        config[filename.replace('.toml', '')] = toml.load(cf)
                        stage_amount += 1

                config["stage_amount"] = stage_amount

                config_file = os.path.join(self.config_dir, 'config.toml')
                with open(config_file, 'w+') as cf:
                    toml.dump(config, cf)

                log(' '.join(['Task saved successfully as', config_file, '\0']), clientsocket)

            elif cmd == 'stage start':
                if self.taskcreator:
                    log('New stage starting', clientsocket)
                    self.taskcreator.start_stage()
                    log('New stage has been started\0', clientsocket)
                else:
                    raise Exception('Task create not starting')

            elif cmd == 'stage stop':
                if self.taskcreator:
                    log('Stage stopping', clientsocket)
                    self.taskcreator.stop_stage()
                    log('Stage has been stopped\0', clientsocket)
                else:
                    raise Exception('Task create not starting')

            else:
                raise Exception('Invalid command')

        except Exception as e:
            log(''.join(['Error: ', str(e), '\0']), clientsocket)
            raise


    def start(self):
        self.sock.listen(10)
        while True:
            # accept connections from outside
            (clientsocket, address) = self.sock.accept()

            self._handle_cmd(clientsocket)
            clientsocket.close()


server = TaskCreatorServer()
server.start()
