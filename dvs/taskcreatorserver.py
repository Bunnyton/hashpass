import socket
import os

from dvs import DVS


def log(msg: str, clientsocket: socket.socket):
    print(msg.replace('\0', ''))
    clientsocket.send(bytes(msg, 'utf-8'))


class DVSServer:
    host = '127.0.0.1'
    port = 17170
    max_buff_size = 4096
    sock = None

    dvs = None
    config_dir = str()

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((self.host, self.port))

    def _handle_cmd(self, clientsocket: socket.socket):
        buf = clientsocket.recv(self.max_buff_size)
        try:
            if not buf:
                return
            cmd = buf.decode().split()
            print(''.join(['Get: ', buf.decode()]))

            if len(cmd) == 2 and cmd[0] == 'start':  # start DVS with config dir
                if self.dvs:
                    raise Exception('Task creating already started')
                if not os.path.exists(cmd[1]):
                    raise Exception(' '.join([cmd[1], "config dir doesn't exist"]))
                self.config_dir = cmd[1]
                self.dvs = DVS(cmd[1])
                log('Task creating\0', clientsocket)

            elif len(cmd) == 1 and cmd[0] == 'stop':
                if self.dvs:
                    del self.dvs
                    self.dvs = None
                    log('Task created successfully\0', clientsocket)

            elif len(cmd) == 2 and cmd[0] == 'stage' and cmd[1] == 'start':
                if self.dvs:
                    log('New stage starting', clientsocket)
                    self.dvs.start_stage()
                    log('New stage has been started\0', clientsocket)
                else:
                    raise Exception('Task create not starting')

            elif len(cmd) == 2 and cmd[0] == 'stage' and cmd[1] == 'stop':
                if self.dvs:
                    log('Stage stopping', clientsocket)
                    self.dvs.stop_stage()
                    log('Stage has been stopped\0', clientsocket)
                else:
                    raise Exception('Task create not starting')

            else:
                raise Exception('Invalid command')

        except Exception as e:
            log(''.join(['Error: ', str(e), '\0']), clientsocket)

    def start(self):
        self.sock.listen(10)
        while True:
            # accept connections from outside
            (clientsocket, address) = self.sock.accept()

            self._handle_cmd(clientsocket)
            clientsocket.close()


dvsserver = DVSServer()
dvsserver.start()
