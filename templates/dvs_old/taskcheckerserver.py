#!/bin/python3

import os
import glob
import toml
import logging
import socket

from simhash import Simhash
from server import Server

from syshelp import readfile

from hooks.engine import cmd_hook, filter_hook
import json

class TaskCheckerServer(Server):
    def __init__(self, config_file="/.hash/.task/config.toml"):
        super().__init__()

        self._cmd = None
        self.curstage_num = 0
        self.is_completed = False
        self._cmd_output_file = "/.hash/.hash.cmd.out"

        with open(config_file, 'r') as cf:
            self.config = toml.load(cf)


    def task_complete(self):
        return 'key'


    def check_change(self, path) -> bool:
        stage_config = self.config[''.join(['stage', str(self.curstage_num)])]

        change = stage_config['changes'][path]
        if path == 'output':
            self.reply_with_logging(stage_config['changes'], self.clientsocket)
            self.reply_with_logging(str(change), self.clientsocket)
            self.reply_with_logging(str(path), self.clientsocket)
            data = readfile(self._cmd_output_file, stage_config["options"]["ignore_date"])

            if self._cmd is None:
                raise Exception("Can't use filter hook without cmd")
            data = filter_hook(data, self._cmd, self.curstage_num)

            self.reply_with_logging(data, self.clientsocket)
            self.reply_with_logging(str(Simhash(data).value), self.clientsocket)
            if Simhash(data).distance(Simhash(change['hash'], from_hash=True)) < 1 - stage_config['options']['output_accuracy']:
                    return True

        else:
            if change['state'] == 'modified' or change['state'] == 'created':
                if change['is_dir']:
                    if os.path.exists(path) and os.path.isdir(path):
                        return True

                elif os.path.exists(path) and os.path.isfile(path):
                    data = readfile(path, stage_config["options"]["ignore_date"])
                    if Simhash(data).distance(Simhash(change['hash'], from_hash=True)) < 1 - stage_config['options']['fs_accuracy']:
                            return True

            else:
                if not os.path.exists(path):
                    return True

        return False


    def check_stage(self) -> bool:
        if self.curstage_num < self.config['stage_amount']:
            stage_config = self.config[''.join(['stage', str(self.curstage_num)])]
            for change in stage_config['changes']:
                if not self.check_change(change):
                    return False

        return True


    def check(self):
        if not self.is_completed and self.check_stage():
            self.curstage_num += 1
            if self.curstage_num >= self.config['stage_amount']:
                self.is_completed = True
                return self.task_complete()
        return None




    def _handle_cmd(self, cmd: list, clientsocket: socket.socket):
        if len(cmd) == 1 and cmd[0] == 'check':
            self.clientsocket = clientsocket
            res = self.check()
            if res is not None: 
                self.reply(res, clientsocket)

        if len(cmd) > 1 and cmd[0] == 'cmd':
            self._cmd = ' '.join(cmd[1::])
            cmds = cmd_hook(' '.join(cmd[1::]), self.curstage_num)
            self.reply(json.dumps(cmds), clientsocket)




server = TaskCheckerServer(config_file="/.hash/.task/config.toml")
server.start()
