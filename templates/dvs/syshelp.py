import subprocess
import shutil
import os
import re

def copy(src, dest, progress_bar=False):
    try:
        if os.path.isdir(src) and not dest.endswith('/'):
            src = str(src + '/').replace('//', '/')
            dest = str(dest + '/').replace('//', '/')


        if dest.endswith('/'):
            os.makedirs(dest, exist_ok=True)

        else:
            os.makedirs(os.path.dirname(dest), exist_ok=True)

        if progress_bar:
            subprocess.run(["rsync", "-a", "-l", "--info=progress2", src, dest])

        else:
            subprocess.run(["rsync", "-a", "-l", src, dest])

    except Exception:
        if not os.path.isfile(src):
            remove(dest_dir)

        raise


def remove(path, missing_ok=True):
    if missing_ok:
        if not os.path.exists(path):
            return

    if os.path.isfile(path):
        os.remove(path)
        
    else:
        shutil.rmtree(path)


def move(src, dest, progress_bar=False):
    copy(src, dest, progress_bar)
    remove(src)
        

def read(s: str, default=None) -> str:
    val = str(input(s))
    while not val:
        if default is not None:
            val = default
            print(' '.join(["Set to", default, "automatically"]))
            break
        
        else:
            val = str(input(s))


    return val


def readfile(path: str, clean_date=False):
    if os.path.isfile(path):
        with open(path, 'r') as f:
            data = str(f.read())

            if clean_date:
                regex = r'\b\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Янв|Фев|Мар|Апр|Май|Июн|Июл|Авг|Сен|Окт|Ноя|Дек)\s+\d{1,2}\s+(\d{4}|\d{2}:\d{2}|\d{2}:\d{2}:\d{2})\b'
                data = re.sub(regex, '', data, flags=re.IGNORECASE)

            print(data, end="\n\n")
            return data

    else:
        return None




# def get_char():
#     fd = sys.stdin.fileno()
#     old_settings = termios.tcgetattr(fd)
#     try:
#         tty.setraw(sys.stdin.fileno())
#         ch = sys.stdin.read(1)
#     finally:
#         termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
#     return ch
# 
# 
# def get_answer(question):
#     ans = ''
#     while ans != 'y' and ans != 'n':
#         print(question, end=' [y/n] ')
#         ans = get_char()
#     
#     return ans
