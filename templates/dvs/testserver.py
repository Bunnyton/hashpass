from server import Server

class Test(Server):
    def _handle_cmd(self, cmd, clientsocket):
        self.reply(str(cmd), clientsocket)
        self.reply(str(cmd), clientsocket)
        self.reply(str(cmd), clientsocket)
        self.reply(str(cmd), clientsocket)



test = Test()
test.start()
