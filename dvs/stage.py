from watchdog.events import FileSystemEventHandler
import watchdog
from watchdog.observers import Observer

from simhash import Simhash

import os.path
import toml

import time # delete me


class Stage():
    def __init__(self, config_file: str, mode='Interactive', fs_analyzer=True, fs_accuracy=0.7, output_analyzer=True, output_accuracy=0.7, observe_list=['/home/anton/LinuxWork/study/8/nirs/dvs/tmp/file', '/usr/bin/', '/usr/local/bin', '/etc/']):
        if observe_list is None:
            observe_list = ['/home/anton/LinuxWork/study/8/nirs/dvs/tmp/file', '/usr/bin/', '/usr/local/bin', '/etc/']

        self._observe_list = dict()
        self._observe_list['files'] = dict()
        self._observe_list['dirs'] = list()
        for ob in observe_list:
            if not os.path.exists(ob) or os.path.isfile(ob):
                pardir = os.path.dirname(ob)
                while not os.path.exists(pardir):
                    pardir = os.path.dirname(pardir)

                self._observe_list['files'][pardir] = ob

            else:
                self._observe_list['dirs'].append(ob)

        if not os.path.exists(os.path.dirname(os.path.abspath(config_file))):
            raise Exception('Config file path incorrect')

        self.config_file = config_file

        self.config = dict()
        self.config['options'] = dict()
        self.config['changes'] = dict()

        self.config['options']['mode'] = mode
        self.config['options']['fs_analyzer'] = fs_analyzer
        self.config['options']['fs_accuracy'] = fs_accuracy
        self.config['options']['observe_list'] = observe_list
        self.config['options']['output_analyzer'] = output_analyzer
        self.config['options']['output_accuracy'] = output_accuracy

        self._observe_processes = list()

    def _observe_dir(self, path, recursive=True):
        if not os.path.exists(path):
            raise Exception('Observe dir path incorrect')

        def fix_change(path: str, state: str, is_dir: bool):
            try:
                if not is_dir:
                    pardir = os.path.dirname(path)
                    if pardir in self._observe_list['files'].keys():
                        if self._observe_list['files'][pardir] != path:
                            return # another file ignore from observe dir of observe file 

                if path in self.config['changes'].keys():
                    if state == 'created':
                        if self.config['changes'][path]['state'] == 'deleted':
                            self.config['changes'].pop(path)
                        else:
                            raise Exception(' '.join(['New state of file', path, 'is', state, 'but prev state is',
                                                      self.config['changes'][path]['state']]))

                    elif state == 'modified':
                        if self.config['changes'][path]['state'] == 'created':
                            self.config['changes'][path] = {'path': path,
                                                            'is_dir': is_dir,
                                                            'pardir': os.path.dirname(path),
                                                            'hash': str(Simhash(path, from_file=True).value),
                                                            'state': 'created'}

                        elif self.config['changes'][path]['state'] == 'modified':
                            self.config['changes'][path] = {'path': path,
                                                            'is_dir': is_dir,
                                                            'pardir': os.path.dirname(path),
                                                            'hash': str(Simhash(path, from_file=True).value),
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
                                                            'hash': str(Simhash(path, from_file=True).value),
                                                            'state': state}

                    elif state == 'modified':
                        self.config['changes'][path] = {'path': path,
                                                        'is_dir': False,
                                                        'pardir': os.path.dirname(path),
                                                        'hash': str(Simhash(path, from_file=True).value),
                                                        'state': state}

                    elif state == 'deleted':
                        self.config['changes'][path] = {'path': path,
                                                        'is_dir': is_dir,
                                                        'pardir': os.path.dirname(path),
                                                        'state': state}
            except Exception as e:
                pass

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
                if event.is_directory == False:
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
        with open(self.config_file, 'w') as cf:
            toml.dump(self.config, cf)

    def __del__(self):
        self.stop()
        # self.config = dict()

        # stage = Stage('./config.toml')
        # stage.start()
        # time.sleep(20)
        # stage.stop()
        # stage.save()
