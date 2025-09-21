import sys
from client import Client
from syshelp import read
import json


class Config():
    def __init__(self):
        self.statusfile = "/.hash/.hash.status"


def handle_cmd(cmd: list):
    try:
        config = Config()
        taskclient = Client()

        if len(cmd) == 0:
            raise Exception("Args num incorrect" )
        # for task creator server
        if cmd[0] == "start":
            if len(cmd) != 1:
                raise Exception("Args num incorrect" )

            taskclient.send_cmd("start") 

        elif cmd[0] == "save":
            if len(cmd) == 1:
                name = read("Enter name of task: ")
                author = read("Enter author of task: ")                     
                version = read("Enter version of task: ", default="latest")
                taskclient.send_cmd(' '.join(["save", name, author, version]))

            else:
                raise Exception("Args num incorrect" )
            
        elif cmd[0] == "action" or cmd[0] == "stage" or cmd[0] == "stop" or cmd[0] == "settings":
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

        elif cmd[0] == "exit":
            if len(cmd) == 1:
                with open(config.statusfile, 'w') as sf:
                    sf.write("stopping")

            else:
                raise Exception("Args num incorrect" )


        elif cmd[0] == "restart":
            if len(cmd) == 1:
                with open(config.statusfile, 'w') as sf:
                    sf.write("restarting")

            else:
                raise Exception("Args num incorrect" )

        elif cmd[0] == "image":
            if len(cmd) == 2 and cmd[1] == "create":
                with open(config.statusfile, 'w') as sf:
                    sf.write("image creating")

            else:
                raise Exception("Args num incorrect" )

        else:
            raise Exception("Unknown args" + str(cmd))

    except Exception as e:
        print(e)


def main():
    handle_cmd(sys.argv[1::])
    # Основной код программы
    

if __name__ == "__main__":
    main()

