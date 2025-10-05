import os
import uuid
import toml
import glob

from pathlib import Path
from threading import Thread
from tabulate import tabulate

from ..settings import Settings

from ..utils import copy,remove,move,read


class Image():
    class Config():
        settings = Settings()
        config_dir = settings.image_config_dir
        config_filename = settings.image_config_filename
        task_work_dirname = settings.task_work_dirname
        task_config_dirname = settings.task_config_dirname
        task_config_filename = settings.task_config_filename
        task_hooks_dirname = settings.task_hooks_dirname

    class Type():
        simple = "simple"
        task = "task"
        base = "base"
    

    def __init__(self, param=None):
        os.makedirs(Image.Config.config_dir, exist_ok=True)

        self.id : str
        self.name : str
        self.author : str
        self.fullname: str
        self.version : str
        self.layers = list()
        self.type: str
        
        image: list
        if param is not None:
            image = Image.get(param)
            if not image:
                raise Exception(' '.join(["Can't find image", param, "locally"]))

            self.id = image['image']['id']
            self.name = image['image']['name']
            self.author = image['image']['author']
            self.version = image['image']['version']
            self.fullname = Image._to_fullname(self.author, self.name, self.version)
            self.layers = image['image']['layers']
            self.type = image['image']['type']

            self.config_dir = os.path.join(Image.Config.config_dir, self.id)
            self.config_path = os.path.join(self.config_dir, Image.Config.config_filename)


    def import_from_fs(self, path: str): 
        # функция отвечает за копирование файловой системы в образ path - путь до каталога, после которого начинается файловая система
        if os.path.isdir(path):
            _path = Path(path)
            all_copy_items = [item for item in _path.iterdir() if item.name != Image.Config.task_work_dirname]
            for copy_item in all_copy_items:
                if os.path.isdir(copy_item):
                    copy(str(copy_item.absolute()) + '/', os.path.join(self.config_dir, str(copy_item.name)) + '/', with_replace=True)

                else:
                    copy(str(copy_item.absolute()), os.path.join(self.config_dir, str(copy_item.name)), with_replace=True)
        else:
            raise Exception("Import path doesn't exist or isn't dir")

    
    def create(self, param=None): #FIXME create must create new image and return them
        if param is None:
            # FIXME update tree with exists image
            self.type = Image.Type.base

        else:
            parent_image = Image.get(param)
            if parent_image:
                self.type = Image.Type.simple
                self.layers = parent_image['image']['layers']
                self.layers.append(parent_image['image']['id'])

            else:
                raise Exception(f"Can't find image {param}")

        
        self.name = read("Enter name of image: ").strip()
        self.author = read("Enter author of image: ").strip()
        self.version = read("Enter version of image: ", default="latest").strip()

        self.fullname = Image._to_fullname(self.author, self.name, self.version)
        if Image.get(self.fullname):
            raise Exception(f"{self.fullname} already exist")

        self.id = str(uuid.uuid4()).replace("-", "")
        self.config_dir = os.path.join(Image.Config.config_dir, self.id)
        self.config_path = os.path.join(self.config_dir, Image.Config.config_filename)
        self.save()

        return self.id


    def delete(self):
        print(f"Deleting {self.fullname}")

        for image in Image.list():
            if self.id in image.layers:
                image.delete()

        if os.path.exists(self.config_dir):
            remove(self.config_dir)

        print(f"✅ Delete {self.fullname} successfull")


    def info(self) -> dict:
        data = dict()
        if os.path.isfile(self.config_path):
            data = toml.load(self.config_path)

        else:
            data["image"] = dict()


        data["image"]["name"] = self.name
        data["image"]["author"] = self.author
        data["image"]["version"] = self.version
        data["image"]["id"] = self.id
        data["image"]["type"] = self.type
        data["image"]["layers"] = self.layers

        return data


    def save(self, is_base_image=False):
        data = self.info()

        os.makedirs(self.config_dir, exist_ok=True)
        with open(self.config_path, "w") as f:
            toml.dump(data, f)

        if is_base_image:
            copy(os.getcwd(), self.config_dir + '/', progress_bar=True)


    def _parse_fullname(fullname: str) -> list: # return [author, name, version]
        try:
            author, name = fullname.split('/')

            if ':' in name:
                name, version = name.split(':')

            else:
                version = 'latest'

            return [author, name, version]

        except Exception():
            raise Exception("Image name incorrect")


    def _to_fullname(*args) -> str:
        if len(args) == 1 and type(args[0]) == dict:
            data = args[0]
            if data.get("image") and data["image"].get("name") \
                and data["image"].get("author") and data["image"].get("version"):
                return data["image"]["author"] + '/' + data["image"]["name"] + ':' + data["image"]["version"]


        elif len(args) == 1 and type(args[0]) == str:
            if ':' in args[0]:
                return args[0]
                
            else:
                return args[0] + ':latest'

        elif len(args) == 3:
            return args[0] + '/' + args[1] + ':' + args[2]

        elif len(args) == 2:
            return args[0] + '/' + args[1] + ':' + 'latest'



        raise Exception("Image incorrect")


    def get(param) -> dict: # return fullname
        if isinstance(param, str):
            if '/' in param:
                author, name, version = Image._parse_fullname(param)
                for file in glob.glob(Image.Config.config_dir + "/**/" + Image.Config.config_filename, recursive=False):
                    temp = toml.load(file)
                    if temp['image']['name'] == name and temp['image']['version'] == version and temp['image']['author'] == author:
                        return temp

            else:
                id = param
                for file in glob.glob(Image.Config.config_dir + "/**/" + Image.Config.config_filename, recursive=False):
                    temp = toml.load(file)

                    if temp['image']['id'] == id:
                        return temp

        return None


    def get_fullname(param) -> str: # return fullname
        manifest = Image.get(param)
        if manifest:
            return Image._to_fullname(manifest['image']['author'], manifest['image']['name'], manifest['image']['name'])

        return None


    def list() -> list: # return [manifest, manifest, ...]
        images = list()
        for file in glob.glob(Image.Config.config_dir + "/**/" + Image.Config.config_filename, recursive=False):
            manifest = toml.load(file)
            if manifest:
                images.append(Image(manifest['image']['id']))

        return images


    def print_list():
        table = [["ID", "NAME", "TYPE", "PARENT IMAGE"]]

        for file in glob.glob(Image.Config.config_dir + "/**/" + Image.Config.config_filename, recursive=False):
            temp = toml.load(file)

            parent_image_fullname = None
            if temp["image"]["layers"]:
                parent_image_fullname = Image.get_fullname(temp["image"]["layers"][-1])

            table.append([temp["image"]["id"]
                          , Image._to_fullname(temp["image"]["author"], temp["image"]["name"], temp["image"]["version"])
                          , temp["image"]["type"], parent_image_fullname])

        print(tabulate(table, headers="firstrow", tablefmt="grid"))


    def load_task_config(self, path: str):
        if self.type == Image.Type.task:
            _ = toml.load(path) # test toml via load
            copy(path, os.path.join(self.config_dir, Image.Config.task_config_dirname, Image.Config.task_config_filename))

        else:
            raise Exception(' '.join(["Image id =", self.id, "is not task image"]))


    def load_task_hooks(self, path: str):
        hooks_dir = os.path.join(self.config_dir, Image.Config.task_work_dirname, Image.Config.task_hooks_dirname)
        copy(path + '/', hooks_dir + '/', with_replace=True)
