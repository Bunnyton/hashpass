import __init__

import time
from watchdog.observers import Observer

def watch_system(path):
    observer = Observer()
    observer.schedule(__init__.Handler(), path=path, recursive=True)
    observer.start()
    return observer

directories=[]
directories.append(watch_system(r"C:/"))

try:
    while True:
        time.sleep(0.1)
except KeyboardInterrupt:
    for i in directories:
        i.stop()
for i in directories:
    i.join()