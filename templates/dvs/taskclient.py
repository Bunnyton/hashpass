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
        task_client = Client()

         # for task check server
        
        # for task creator server
        if cmd[0] == "start":
            if len(cmd) != 1:
                raise Exception("Args num incorrect" )

            task_client.send_cmd("start") 

        elif cmd[0] == "save":
            if len(cmd) == 1:
                name = read("Enter name of task: ")
                author = read("Enter author of task: ")                     
                version = read("Enter version of task: ", default="latest")
                task_client.send_cmd(' '.join(["save", name, author, version]))

            else:
                raise Exception("Args num incorrect" )
            
        elif cmd[0] == "check" or cmd[0] == "stage" or cmd[0] == "stop" or cmd[0] == "settings":
            task_client.send_cmd(' '.join(cmd[0::]))

        elif cmd[0] == "cmd":
            res = task_client.send_cmd(' '.join(cmd[0::]), output=False)
            print(res)
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

        else:
            raise Exception("Unknown args")

    except Exception as e:
        print(e)


def main():
    handle_cmd(sys.argv[1::])
    # Основной код программы
    

if __name__ == "__main__":
    main()

