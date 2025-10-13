import os
import uuid
import toml
import glob

from pathlib import Path
from tabulate import tabulate

from hashpass.settings import Settings

from hashpass.utils import copy, remove, read


class Image:
    class Config:
        settings = Settings()
        config_dir = settings.image_config_dir
        config_filename = settings.image_config_filename
        task_work_dirname = settings.task_work_dirname
        task_config_dirname = settings.task_config_dirname
        task_config_filename = settings.task_config_filename
        task_hooks_dirname = settings.task_hooks_dirname
        config_layer_base = settings.image_config_layer_base
        config_layer_taskcreator = settings.image_config_layer_base
        config_layer_taskchecker = settings.image_config_layer_base

    class Type:
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
        self.hashsum: str = ""
        self.layers = list()
        self.type: str
        
        if param is not None:
            manifest: dict
            if Image.check_manifest(param):
                manifest = param

            else:
                manifest = Image.get_manifest(param)
                if not manifest:
                    raise Exception(' '.join(["Can't find image", param, "locally"]))

            self.id = manifest['image']['id']
            self.name = manifest['image']['name']
            self.author = manifest['image']['author']
            self.version = manifest['image']['version']
            self.fullname = Image._to_fullname(self.author, self.name, self.version)
            self.layers = manifest['image']['layers']
            self.type = manifest['image']['type']

            if 'hashsum' in manifest['image']:
                self.hashsum = manifest['image']['hashsum']

            self.config_dir = os.path.join(Image.Config.config_dir, self.id)
            self.config_path = os.path.join(self.config_dir, Image.Config.config_filename)


    def import_from_fs(self, path: str): #FIXME try rsync --delete
        # функция отвечает за копирование файловой системы в образ path - путь до каталога, после которого начинается файловая система
        if os.path.isdir(path):
            _path = Path(path)
            all_copy_items = [item for item in _path.iterdir() if item.name != Image.Config.task_work_dirname]
            for copy_item in all_copy_items:
                if os.path.isdir(copy_item):
                    copy(str(copy_item.absolute()) + '/', os.path.join(self.config_dir, str(copy_item.name)) + '/', with_replace=True)

                else:
                    copy(str(copy_item.absolute()), os.path.join(self.config_dir, str(copy_item.name)), with_replace=True)

            if os.path.exists(os.path.join(path, Image.Config.task_hooks_dirname)):
                copy(os.path.join(path, Image.Config.task_hooks_dirname)
                     , os.path.join(self.config_dir, Image.Config.task_hooks_dirname), with_replace=True)

        else:
            raise Exception("Import path doesn't exist or isn't dir")


    def exist(param) -> bool:
        try:
            Image(param)
            return True
        except:
            return False
    

    def create(self, param=None): #FIXME create must create new image and return them
        if param is None:
            # FIXME update tree with exists image
            self.type = Image.Type.base

        else:
            parent_image = Image(param)
            if parent_image:
                self.type = Image.Type.simple
                self.layers = parent_image.layers
                self.layers.append(parent_image.id)

        
        self.name = read("Enter name of image: ").strip()
        self.author = read("Enter author of image: ").strip()
        self.version = read("Enter version of image: ", default="latest").strip()

        self.fullname = Image._to_fullname(self.author, self.name, self.version)
        if Image.exist(self.fullname):
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
        data["image"]["hashsum"] = self.hashsum

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


    def check_manifest(manifest: dict):
        if isinstance(manifest, dict) and 'image' in manifest:
            for _ in ['id', 'author', 'name', 'version']:
                if _ not in manifest['image']:
                    return False

            return True

        return False


    def get_manifest(param) -> dict:
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

        elif Image.check_manifest(param):
            return param

        return None


    def get_fullname(param) -> str|None:
        try:
            return Image(param).fullname
        except:
            return None


    def get_hashsum(param) -> str|None:
        try:
            return Image(param).hashsum
        except:
            return None


    def list(manifests=False) -> list: # return all images
        images = list()
        for file in glob.glob(Image.Config.config_dir + "/**/" + Image.Config.config_filename, recursive=False):
            manifest = toml.load(file)
            if Image.check_manifest(manifest):
                if manifests:
                    images.append(manifest)
                else:
                    images.append(Image(manifest))

        return images


    def print_images(*manifests):
        if not manifests:
            manifests = Image.list(manifests=True)

        table = [["ID", "NAME", "TYPE", "PARENT IMAGE", "HASHSUM"]]

        for manifest in manifests:
            parent_image_name = None
            if manifest["image"]["layers"]:
                parent_image_name = Image.get_fullname(manifest["image"]["layers"][-1])
                if not parent_image_name:
                    parent_image_name = manifest["image"]["layers"][-1]

            hashsum = "not pushed"
            if "hashsum" in manifest["image"] and manifest["image"]["hashsum"]:
                hashsum = manifest["image"]["hashsum"]

            table.append([manifest["image"]["id"][:16]
                            , Image.get_fullname(manifest)
                            , manifest["image"]["type"]
                            , parent_image_name
                            , hashsum[:16]])

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
