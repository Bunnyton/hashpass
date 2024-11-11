import os.path
import socket
import time
import sys

class TaskCreatorClient:
    host = '127.0.0.1'
    port = 17170
    max_buff_size = 4096
    timeout = 10
    sock = None

    def connect(self):
        start_time = time.time()
        self.sock = socket.socket()
        while self.timeout > time.time() - start_time:
            try:
                self.sock.connect((self.host, self.port))
            except:
                pass
            else:
                break
        else:
            raise TimeoutError("Can't connect to server")

    def send_cmd(self, cmd: list):
        if len(cmd) == 2 and cmd[0] == 'start':
            if os.path.exists(cmd[1]) and os.path.isdir(cmd[1]):
                cmd = ['start', os.path.abspath(cmd[1])]
            else:
                raise Exception(' '.join([cmd[1], "config dir doesn't exist"]))
        self.connect()
        self.sock.send(bytes(' '.join(cmd), 'utf-8'))

        response = self.sock.recv(self.max_buff_size)
        print(response.decode().replace('\0', ''))
        while b'\0' not in response:
            response = self.sock.recv(self.max_buff_size)
            print(response.decode().replace('\0', ''))

        self.sock.close()


tcc = TaskCreatorClient()
tcc.send_cmd(sys.argv[1:])
