import watchdog
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from simhash import Simhash

import os
import toml

from syshelp import readfile
import hooks


class Stage():
    class Config():
        cmd_output_file = "/.hash/.hash.cmd.out"

    def __init__(self, result_file: str, config_file: str, _num: int):
        if os.path.isfile(config_file):
            with open(config_file, 'r') as sf:
                self.config = toml.load(sf)
            self.config["changes"] = dict()
        else:
            raise Exception(' '.join(["Can't read stage config file", config_file]))

        self._cmd = None #FIXME upgrade cmd handlers
        self._num = _num
        self._observe_processes = list()
        self._observe_list = dict()
        self._observe_list['files'] = dict()
        self._observe_list['dirs'] = list()

        for ob in self.config["observe_list"]:
            if not os.path.exists(ob) or os.path.isfile(ob):
                pardir = os.path.dirname(ob)
                while not os.path.exists(pardir):
                    pardir = os.path.dirname(pardir)

                self._observe_list['files'][pardir] = ob #FIXME

            else:
                self._observe_list['dirs'].append(ob)

        if self.config["options"]["output_analyzer"]:
            self._observe_list['files'][os.path.dirname(Stage.Config.cmd_output_file)] = Stage.Config.cmd_output_file

        if not os.path.exists(os.path.dirname(os.path.abspath(config_file))):
            raise Exception('Config file path incorrect')

        self.result_file = result_file


    def _observe_dir(self, path, recursive=True):
        if not os.path.exists(path):
            raise Exception('Observe dir path incorrect')

        def fix_change(path: str, state: str, is_dir: bool):
            try:
                for exclude_item in self.config["exclude_list"]:
                    if exclude_item.startswith('/'):
                        if path.startswith('/' + exclude_item.strip('/').replace('*', '')):
                            return

                    elif path.endswith(exclude_item.strip('/').replace('*', '')):
                        return


                if not is_dir:
                    pardir = os.path.dirname(path) # FIXME dirs in list for pardir
                    if pardir in self._observe_list['files'].keys():
                        if self._observe_list['files'][pardir] != path:
                            return # another file ignore from observe dir of observe file 

                
                data = readfile(path, self.config["options"]["ignore_date"])
                if self._cmd is not None:
                    raise Exception("Cmd is None, can't use filter function")
                data = hooks.engine.filter_hook(data, self._cmd, self._num)

                if path in self.config['changes'].keys():
                    if state == 'created':
                        if self.config['changes'][path]['state'] == 'deleted':
                            self.config['changes'].pop(path)
                        else:
                            raise Exception(' '.join(['New state of file', path, 'is', state
                                                    , 'but prev state is'
                                                    , self.config['changes'][path]['state']]))

                    elif state == 'modified':
                        if self.config['changes'][path]['state'] == 'created':
                            self.config['changes'][path] = {'path': path,
                                                            'is_dir': is_dir,
                                                            'pardir': os.path.dirname(path),
                                                            'hash': str(Simhash(data).value),
                                                            'state': 'created'}

                        elif self.config['changes'][path]['state'] == 'modified':
                            self.config['changes'][path] = {'path': path,
                                                            'is_dir': is_dir,
                                                            'pardir': os.path.dirname(path),
                                                            'hash': str(Simhash(data).value),
                                                            'state': 'modified'}

                        elif self.config['changes'][path]['state'] == 'deleted':
                            raise Exception(' '.join(['New state of file', path, 'is', state, 'but prev state is deleted',
                                                      self.config['changes'][path]['state']]))

                    elif state == 'deleted':
                        if self.config['changes'][path]['state'] == 'created':
                            self.config['changes'].pop(path)

                        elif self.config['changes'][path]['state'] == 'modified':
                            self.config['changes'][path] = {'path': path,
                                                            'is_dir': is_dir,
                                                            'pardir': os.path.dirname(path),
                                                            'state': 'deleted'}

                    else:
                        raise Exception(' '.join(['New state of file', path, 'is', state, 'but prev state is',
                                                  self.config['changes'][path]['state']]))

                else:
                    if state == 'created':
                        if is_dir:
                            self.config['changes'][path] = {'path': path,
                                                            'is_dir': True,
                                                            'pardir': os.path.dirname(path),
                                                            'state': state}
                        else:
                            self.config['changes'][path] = {'path': path,
                                                            'is_dir': False,
                                                            'pardir': os.path.dirname(path),
                                                            'hash': str(Simhash(data).value),
                                                            'state': state}

                    elif state == 'modified':
                        self.config['changes'][path] = {'path': path,
                                                        'is_dir': False,
                                                        'pardir': os.path.dirname(path),
                                                        'hash': str(Simhash(data).value),
                                                        'state': state}

                    elif state == 'deleted':
                        self.config['changes'][path] = {'path': path,
                                                        'is_dir': is_dir,
                                                        'pardir': os.path.dirname(path),
                                                        'state': state}
            except Exception:
                raise

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                print("cre", str(event.src_path))
                fix_change(event.src_path, 'created', event.is_directory)

                # app(str(event.src_path))

            def on_deleted(self, event):
                print("del", str(event.src_path))
                # self.changes['deleted'] = str(event.src_path)
                fix_change(event.src_path, 'deleted', event.is_directory)
                # data.pop(way)

            def on_modified(self, event):
                print("mod", str(event.src_path))
                # self.changes['modified'] = str(event.src_path)
                if not event.is_directory:
                    fix_change(event.src_path, 'modified', False)
                # app(str(event.src_path))

            def on_moved(self, event):
                print("mov", str(event.src_path))
                # app(str(event.src_path))
                fix_change(event.src_path, 'deleted', event.is_directory)
                fix_change(event.dest_path, 'created', event.is_directory)

        observer = Observer()
        observer.schedule(Handler(), path=path, recursive=True)
        observer.start()

        return observer

    def start(self):
        for dir in self._observe_list['dirs']:
            self._observe_processes.append(self._observe_dir(dir, recursive=True))

        for dir in self._observe_list['files'].keys():
            self._observe_processes.append(self._observe_dir(dir, recursive=False))


    def stop(self):
        for proc in self._observe_processes:
            if proc:
                proc.stop()
            self._observe_processes.remove(proc)
            # proc.join()

    def save(self):
        if Stage.Config.cmd_output_file in self.config['changes'].keys():
            self.config['changes']['output'] = self.config['changes'][Stage.Config.cmd_output_file]
            del self.config['changes'][Stage.Config.cmd_output_file]

        with open(self.result_file, 'w') as cf:
            toml.dump(self.config, cf)

    def __del__(self):
        self.stop()
        # self.config = dict()

        # stage = Stage('./config.toml')
        # stage.start()
        # time.sleep(20)
        # stage.stop()
        # stage.save()
