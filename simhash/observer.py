from watchdog.events import FileSystemEventHandler
from checking_result import check_result
import observer
import time
from watchdog.observers import Observer

def watch_system(path):
    observer = Observer()
    observer.schedule(Handler(), path=path, recursive=True)
    observer.start()
    return observer
    
class Handler(FileSystemEventHandler):
    def on_created(self, event):
        check_result(str(event.src_path))

    def on_deleted(self, event):
        check_result(str(event.src_path))

    def on_modified(self, event):
        check_result(str(event.src_path))

    def on_moved(self, event):
        check_result(str(event.src_path))


directories=[] #!#
directories.append(watch_system(r"/home/lev/hashpass/simhash"))

try:
    while True:
        time.sleep(0.1)
except KeyboardInterrupt:
    for i in directories:
        i.stop()
for i in directories:
    i.join()
