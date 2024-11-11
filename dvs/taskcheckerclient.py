import os.path
import socket
import time


class TaskCheckerClient():
    host = '127.0.0.1'
    port = 17171
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

    def send_cmd(self, cmd: str):
        self.connect()
        self.sock.send(bytes(cmd, 'utf-8'))

        response = self.sock.recv(self.max_buff_size)
        print(response.decode().replace('\0', ''))
        while b'\0' not in response:
            response = self.sock.recv(self.max_buff_size)
            print(response.decode().replace('\0', ''))

        self.sock.close()


tcc = TaskCheckerClient()
tcc.send_cmd("check")
