from watchdog.events import FileSystemEventHandler
import toml
import time
from checking_result import check_result
import observer
from watchdog.observers import Observer

def watch_system(path):
    observer = Observer()
    observer.schedule(Handler(), path=path, recursive=True)
    observer.start()
    return observer
    
class Handler(FileSystemEventHandler):
    def on_created(self, event):
        #print("cre", str(event.src_path))
        check_result(str(event.src_path))

    #def on_deleted(self, event):
        #print("del", str(event.src_path))
        #check_result(str(event.src_path))

    def on_modified(self, event):
        #print("mod", str(event.src_path))
        check_result(str(event.src_path))

    def on_moved(self, event):
        #print("mov", str(event.src_path))
        check_result(str(event.src_path))

def start_observe():
    with open("config.toml","r+") as f:
        config=toml.load(f)
    directories=[]
    for i in config['task']['ways']: #!#
        directories.append(watch_system(i))

    try:
        while True:
            time.sleep(0.01)
    except KeyboardInterrupt:
        for i in directories:
            i.stop()
    for i in directories:
        i.join()
            
start_observe()
