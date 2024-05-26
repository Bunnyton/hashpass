import sys
import toml
from simhash_base import get_simhash
from watchdog.events import FileSystemEventHandler
import time
from watchdog.observers import Observer

stop=0
directories=[]
stage=1 #!#

with open("config.toml","r+") as f:
    config=toml.load(f)
    answers=config['task']['hashes']
    ways=config['task']['ways']
    stage_final=len(answers)

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
    for i in config['task']['ways']: #!#
        directories.append(watch_system(i))

    try:
        while True:
            global stop
            if stop==True:
                break
            time.sleep(0.01)
    except KeyboardInterrupt:
        for i in directories:
            i.stop()

def check_result(result):
    global stage
    if (result)==ways[stage-1] and stage <= stage_final:
        data_1 = get_simhash(result)
        data_2 = get_simhash(answers[stage-1])
        if data_1.distance(data_2) <= 10:
            stage += 1
            if stage == stage_final+1:
                print("Done")
                global stop
                stop=True
                for i in directories:
                    i.stop()
                sys.exit() #не работает...
                # если результат достиг этапа, то ...
            
            
start_observe()
