import socket
import os
import logging

from abc import ABC, abstractmethod


class Server(ABC):
    def __init__(self, host="127.0.0.1", max_buff_size=4096):
        self.host = host
        self.max_buff_size = max_buff_size
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        self.start_logging()

        self.portfile = "/.hash/.server.port"
        self.bind_with_random_port()


    def start_logging(self):
        self.logger = logging.getLogger("Logger")
        self.logger.setLevel(logging.DEBUG)
        self.formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')


    def bind_with_random_port(self):
        port = 17212
        max_port = port + 1000
        while port < max_port:
            try:
                self.sock.bind((self.host, port))
                self.port = port

                os.makedirs(os.path.dirname(self.portfile), exist_ok=True)
                with open(self.portfile, "w") as pf:
                    pf.write(str(self.port))

                return

            except OSError:
                port += 1

        raise Exception("Can't bind with any port")


    def reply(self, msg: str, clientsocket: socket.socket):
        clientsocket.send(bytes(msg + '\0', 'utf-8'))


    def reply_with_logging(self, msg: str, clientsocket: socket.socket, level=logging.INFO):
        log_message = self.formatter.format(logging.LogRecord(name=self.logger.name, level=level, pathname=''
                                                            , lineno=0, msg=msg, args=(), exc_info=None))
        self.reply(log_message, clientsocket)
        self.logger.log(level, msg)


    def get_cmd(self, clientsocket: socket.socket):
        while True:
            buf = clientsocket.recv(self.max_buff_size)
            if buf:
                cmd = buf.decode().strip('\0').split()
                return cmd


    @abstractmethod
    def _handle_cmd(self, cmd: list, clientsocket: socket.socket):
        pass

    
    def start(self):
        self.sock.listen(5)
        while True:
            try:
                (clientsocket, address) = self.sock.accept()
                try:
                    cmd = self.get_cmd(clientsocket)
                    self._handle_cmd(cmd, clientsocket)

                except Exception as e:
                    self.reply_with_logging(e, clientsocket, level=logging.ERROR)

            except Exception as e:
                self.logger.log(logging.ERROR, e)
                raise

            finally:
                clientsocket.close()
