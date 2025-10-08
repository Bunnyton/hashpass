import subprocess
import hashlib
import shutil
import os
import re

def copy(src, dest, progress_bar=False, with_replace=True, clear_copy=False):
    try:
        args = list()

        if progress_bar:
            args.append("--info=progress2")

        if not with_replace:
            args.append("--ignore-existing")

        if clear_copy:
            args.append("--delete")

        subprocess.run(["rsync", "-a", "--mkpath", *args, src, dest])


    except Exception:
        raise


def remove(path, missing_ok=True):
    if missing_ok:
        if not os.path.exists(path):
            return

    if os.path.isfile(path):
        os.remove(path)

    elif os.path.islink(path):
        os.unlink(path)

    else:
        def handle_remove_error(func, path, exc_info):
            print(f"Не удалось удалить {path}: {exc_info[1]}")

        shutil.rmtree(path, onerror=handle_remove_error)


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


def readfile(path: str):
    if os.path.isfile(path):
        with open(path, 'r', encoding='utf-8') as f:
            data = f.read()

            return data

    else:
        return None


def hashsum(path: str):
    if os.path.exists(path):
        return hashlib.sha256(open(path, 'rb').read()).hexdigest()

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
