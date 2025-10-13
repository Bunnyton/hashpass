import sys
from client import Client
import json


class Config():
    def __init__(self):
        self.statusfile = "/.hash/.hash.status"


def handle_cmd(cmd: list):
    try:
        config = Config()
        taskclient = Client()

        if len(cmd) == 0:
            raise Exception("Args num incorrect")
        # for task creator server

        if cmd[0] == "task":
            if len(cmd) != 2:
                    raise Exception("Args num incorrect")

            if cmd[1] == "start" or cmd[1] == "save" or cmd[1] == "stop" or cmd[1] == "settings":
                    taskclient.send_cmd(cmd[1]) 

            elif cmd[1] == "restart":
                with open(config.statusfile, 'w') as sf:
                    sf.write("restarting")

            elif cmd[1] == "play":
                with open(config.statusfile, 'w') as sf:
                    sf.write("task playing")

            elif cmd[1] == "exit":
                with open(config.statusfile, 'w') as sf:
                    sf.write("stopping")

            else:
                raise Exception("Unknown args")
            
        elif cmd[0] == "action" or cmd[0] == "stage":
            taskclient.send_cmd(' '.join(cmd))

        elif cmd[0] == "check" or cmd[0] == "cmd":
            res = taskclient.send_cmd(' '.join(cmd), output=False)
            if res:
                for msg in res:
                    try:
                        cmds = json.loads(msg)
                        return cmds
                    except:
                        pass

        elif cmd[0] == "image":
            if len(cmd) != 2:
                raise Exception("Args num incorrect")

            if len(cmd) == 2 and cmd[1] == "save":
                with open(config.statusfile, 'w') as sf:
                    sf.write("image saving")

            elif len(cmd) == 2 and cmd[1] == "update":
                with open(config.statusfile, 'w') as sf:
                    sf.write("image updating")

            else:
                raise Exception("Unknown args")

        else:
            raise Exception("Unknown args")

    except Exception as e:
        print(e)


def main():
    handle_cmd(sys.argv[1::])
    # Основной код программы
    

if __name__ == "__main__":
    main()

