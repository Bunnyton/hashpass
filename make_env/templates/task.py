#!/bin/python3

import sys
import os


def main():
    if len(sys.argv) == 2:
        if sys.argv[1] == 'stop':
            with open("/.hash/.hash.status", "w") as f:
                f.write("stopping")

if __name__ == "__main__":
    main()
