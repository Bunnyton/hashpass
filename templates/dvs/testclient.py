import sys
from client import Client
from syshelp import read


class Config():
    def __init__(self):
        self.statusfile = "/.hash/.hash.status"


def main():
    client = Client()
    res = client.send_cmd('cmd', output=True)
    print(res)


if __name__ == "__main__":
    main()

