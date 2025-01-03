#!/bin/python3 

import socket
import os
import glob
import toml

import hooks
import json
from task import Task
from server import Server
from syshelp import copy


class TaskCreatorServer(Server):
    def __init__(self):
        super().__init__()

        self.task = None

        self.system_config_dir = "/.hash/.task"
        self.user_config_dir = "/.hash/config"
        self.hooks_dir = "/.hash/bin/hooks"
        os.makedirs(self.system_config_dir, exist_ok=True)


    def _cmd_start(self, cmd: list, clientsocket: socket.socket):
        if len(cmd) != 1 :
            raise Exception("Args num incorrect")

        if self.task:
            raise Exception('Task creating already started')

        self.task = Task(self.user_config_dir)

        self.reply_with_logging('Task creating has been started', clientsocket)


    def _stop(self, clientsocket):
        if self.task:
            del self.task
            self.task = None

    def _cmd_stop(self, cmd: list, clientsocket: socket.socket):
        if len(cmd) != 1:
            raise Exception("Args num incorrect")

        self._stop(clientsocket)
        self.reply_with_logging(' '.join(['Task created successfully, please, verify config'
                                        , '"' + self.user_config_dir + '"']), clientsocket)



    def _cmd_stage(self, cmd: list, clientsocket: socket.socket):
        if len(cmd) != 2:
            raise Exception("Args num incorrect")

        if not self.task:
                raise Exception("Task creating hasn't be started")

        if cmd[1] == "start":
            self.reply_with_logging('New stage starting', clientsocket)
            self.task.start_stage()
            self.reply_with_logging('New stage has been started', clientsocket)

        elif cmd[1] == "stop":
            self.reply_with_logging('Stage stopping', clientsocket)
            self.task.stop_stage()
            self.reply_with_logging('Stage has been stopped', clientsocket)

        elif cmd[1] == "settings":
            if self.task._curstage is None:
                self.task.dump_settings(self.task.stage_config_file)
                self.reply_with_logging(' '.join(['Edit stage settings from file', self.task.stage_config_file]), clientsocket)

            else:
                raise Exception("Stage already started")

        else:
            raise Exception("Invalid command")


    def _load_to_system_config(self, cmd: list, clientsocket: socket.socket):
        config = dict()
        stage_counter = 0
        for stage_config in glob.glob(os.path.join(self.user_config_dir, "stage[0-9]*.toml")):
            with open(os.path.join(self.user_config_dir, stage_config), 'r') as cf:
                config[os.path.basename(stage_config).replace('.toml', '')] = toml.load(cf)
                stage_counter += 1

            config["stage_amount"] = stage_counter
            config["name"] = cmd[1]
            config["author"] = cmd[2]
            config["version"] = cmd[3]

            config_file = os.path.join(self.system_config_dir, config["name"] + ".toml")
            with open(config_file, "w+") as cf:
                toml.dump(config, cf)

            copy(self.hooks_dir, os.path.join(self.system_config_dir, config["name"] + "_hooks"))
            self.reply_with_logging(' '.join(['Task saved successfully as', config_file]), clientsocket)


    def _cmd_save(self, cmd: list, clientsocket: socket.socket):
        # structure of cmd : [save, name, author, version]
        if len(cmd) != 4:
            raise Exception("Args num incorrect")

        self._stop(clientsocket)
        self._load_to_system_config(cmd, clientsocket)


    def _cmd_settings(self, cmd: list, clientsocket: socket.socket):
        if len(cmd) != 1:
            raise Exception("Args num incorrect")

        if self.task:
            self.reply_with_logging(' '.join(['Edit stage settings from file', self.task.config_file]), clientsocket)

        else:
            raise Exception("Task must be started for setting them")


    def _cmd_hooks(self, cmd: list, clientsocket: socket.socket):
        if len(cmd) != 1:
            raise Exception("Args num incorrect")

        if self.task:
            self.reply_with_logging(' '.join(['Add hooks to dir', self.task.hooks_dir]), clientsocket)

        else:
            raise Exception("Task must be started for setting them")


    def _cmd_cmd(self, cmd: list, clientsocket: socket.socket):
        if self.task:
            if len(cmd) == 1:
                raise Exception("Args num incorrect")

            if self.task._curstage:
                self.task._curstage._cmd = ' '.join(cmd[1::])

            cmds = hooks.engine.cmd_hook(' '.join(cmd[1::]), self.task._stagenum)
            self.reply(json.dumps(cmds), clientsocket)


    def _handle_cmd(self, cmd: list, clientsocket: socket.socket):
        if cmd[0] == "start":
            self._cmd_start(cmd, clientsocket)

        elif cmd[0] == "stop":
            self._cmd_stop(cmd, clientsocket)

        elif cmd[0] == "settings":
            self._cmd_settings(cmd, clientsocket)

        elif cmd[0] == "hooks":
            self._cmd_hooks(cmd, clientsocket)

        elif cmd[0] == "save": 
            self._cmd_save(cmd, clientsocket)

        elif cmd[0] == "stage":
            self._cmd_stage(cmd, clientsocket)

        elif cmd[0] == "cmd":
            self._cmd_cmd(cmd, clientsocket)

        else:
            raise Exception("Invalid command")



server = TaskCreatorServer()
server.start()
