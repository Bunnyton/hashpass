import sys
import toml
from simhash_base import get_simhash
from watchdog.events import FileSystemEventHandler
import time
from watchdog.observers import Observer

stop=0
directories=[]
stage=1 #!#
config=0
check={}
data={}

with open("config.toml","r+") as f:
    config=toml.load(f)
    config_1=config['stage_'+str(stage)]
    ways=config_1.keys()
    hashes=config_1.values()
    for i in hashes:
        data.update({i:''})
    stage_final=int(config["number_of_stages"])

def check_result(result):
    global stage
    global data
    global ways
    global hashes
    global config
    if ((result)in ways) and (stage <= stage_final):
        data_1 = get_simhash(result)
        for data_ in hashes:
            data_2=get_simhash(data_)
            if data_1.distance(data_2) <= 10:
                data[data_]=result
                break
    
    if stage == stage_final:
        print("Done")
        global stop
        stop=True
        for i in directories:
            i.stop()
        sys.exit() 
    elif (list(data.values()).count(""))==0:
        data={}
        stage+=1
        config=config['stage_'+str(stage)]
        ways=config.keys()
        hashes=config.values()
        for i in hashes:
            data.update({i:''})

def watch_system(path):
    observer = Observer()
    observer.schedule(Handler(), path=path, recursive=True)
    observer.start()
    return observer
    
class Handler(FileSystemEventHandler):
    def on_created(self, event):
        print("cre", str(event.src_path))
        check_result(str(event.src_path))

    #def on_deleted(self, event):
        #print("del", str(event.src_path))
        #check_result(str(event.src_path))

    def on_modified(self, event):
        print("mod", str(event.src_path))
        check_result(str(event.src_path))

    def on_moved(self, event):
        print("mov", str(event.src_path))
        check_result(str(event.src_path))

def start_observe():
    with open("folders.txt","r+") as f:
        folders=f.read().split()
    for i in folders: #!#
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

            
            
start_observe()
