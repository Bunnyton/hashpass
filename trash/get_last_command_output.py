#!/bin/python3

import sys
import os


def get_last_cmd_out(filename):
    with open(filename, 'r') as f:
        text = f.readlines()
        counter = len(text) - 1
        spec_counter = 2
        for line in text[::-1]:
            if 'ξ' in line:
                if spec_counter == 1:
                    if counter == len(text) - 1:
                        return None
                    else:
                        return ''.join(text[counter+1:len(text)-2:1]).strip()
                else:
                    spec_counter -= 1
            counter -= 1

    return None

print(os.system("cat $HOME/.bash_history | tail -1 | sed -E 's/^\s*[0-9]*\s*//g'"))
print(get_last_cmd_out(sys.argv[1]))
