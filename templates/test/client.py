import socket
import os
import time


class Client():
    def __init__(self, host="127.0.0.1", max_buff_size=4096, timeout=1):
        self.host = host
        self.portfile = "/.hash/.server.port"
        self.port = self._get_port()
        self.max_buff_size = max_buff_size
        self.timeout = timeout


    def _get_port(self):
        try:
            with open(self.portfile, "r") as pf:
                return int(pf.read())

        except:
            raise Exception("Server doesn't work")


    def connect(self):
        start_time = time.time()
        self.sock = socket.socket()
        while self.timeout > time.time() - start_time:
            try:
                self.sock.connect((self.host, self.port))
                return
            except:
                raise
        raise TimeoutError("Can't connect to server")


    def send_cmd(self, cmd: str, output=True):
        self.connect()
        response = list()
        try:
            self.sock.send(bytes(cmd, 'utf-8'))

            while True:
                res = self.sock.recv(self.max_buff_size)
                if res:
                    if output:
                        print(res.decode())

                    response.append(res)

                else:
                    break

        except Exception as e:
            raise
        
        finally:
            self.sock.close()
            return response
