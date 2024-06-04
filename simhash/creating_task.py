from watchdog.events import FileSystemEventHandler
import toml
import time
import os
import sys
from simhash_base import get_simhash
from watchdog.observers import Observer
stop=0
directories=[]
folders=[]
stage=1
data={}
config={}
def deleted(way):
    data.pop(way)
def is_folder(way):
    return os.path.isdir(way)

def app(way):
    global config
    global data
    global stage
    if is_folder(way):
        if (way not in folders):
            folders.append(way)
    else:
        if way!="/home/lev/hashpass/simhash/flag":
            data.update({way:str(get_simhash(way).value)})  
        else:
            flag=''
            with open("flag","r") as f:
                flag=str(f.read())
            config.update({"stage_"+str(stage):data})
            
                
            data={}
            stage+=1
            print("Стадия записана")
            if "stop" in flag:
                with open("config.toml", "r+") as f:
                    #config=toml.load(f)
                    config.update({"number_of_stages":stage-1})
                    toml.dump(config,f)
                print("Упражнение записано")
                global stop
                stop=True
                for i in directories:
                    i.stop()
                
            
    
def watch_system(path):
    observer = Observer()
    observer.schedule(Handler(), path=path, recursive=True)
    observer.start()
    return observer
    
class Handler(FileSystemEventHandler):
    def on_created(self, event):
        print("cre", str(event.src_path))
        app(str(event.src_path))

    def on_deleted(self, event):
        print("del", str(event.src_path))
        deleted(str(event.src_path))

    def on_modified(self, event):
        print("mod", str(event.src_path))
        app(str(event.src_path))

    def on_moved(self, event):
        print("mov", str(event.src_path))
        app(str(event.src_path))

def start_observe():
    with open("folders.txt","r+") as f:
        config=f.read().split()
    for i in config:
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
    for i in directories:
        i.join()

print("Введите директории для отслеживания задания в документ folders.txt, каждая на отдельной строке.\nПотом нажмите Enter\nДля завершения записи этапа напишите в другом окне 'echo '' > flag'\nДля завершения записи задания напишите в другом окне 'echo 'stop' > flag'")
a=input()
start_observe()
