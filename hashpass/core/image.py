import os
import uuid
import toml
import glob

from pathlib import Path
from tabulate import tabulate

from hashpass.settings import Settings

from hashpass.utils import copy, remove, read, move, get_machine_arch


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
        config_layer_basesettings = settings.image_config_layer_basesettings
        config_layer_taskcreator = settings.image_config_layer_taskcreator
        config_layer_taskchecker = settings.image_config_layer_taskchecker
        exclude_list = settings.image_exclude_list

    class Type:
        simple = "simple"
        task = "task"
        base = "base"
    

    def __init__(self, param=None, arch=get_machine_arch()):
        os.makedirs(Image.Config.config_dir, exist_ok=True)

        self._id: str
        self._layers = list()
        self._type: str
        self._arch: str = arch

        self.name: str
        self.author: str
        self.fullname: str
        self.version: str

        if param is not None:
            manifest: dict
            if Image.check_manifest(param):
                manifest = param

            else:
                manifest = Image.get_manifest(param, arch)

            self._id = manifest['image']['id']
            self._layers = manifest['image']['layers']
            self._type = manifest['image']['type']

            self.name = manifest['image']['name']
            self.author = manifest['image']['author']
            self.version = manifest['image']['version']
            self.fullname = Image.to_fullname(self.author, self.name, self.version)


            if 'arch' in manifest['image']:
                self._arch = manifest['image']['arch']

            self._config_dir = os.path.join(Image.Config.config_dir, self._id)
            self._config_path = os.path.join(self._config_dir, Image.Config.config_filename)

    def set_id(self, id: str):
        self._id = id
        new_config_dir = os.path.join(Image.Config.config_dir, self._id)
        new_config_path = os.path.join(new_config_dir, Image.Config.config_filename)

        move(self._config_dir, new_config_dir)

        self._config_dir = new_config_dir
        self._config_path = new_config_path
        self.save()

    def set_arch(self, arch: str):
        self._arch = arch
        self.save()

    def set_type(self, type):
        self._type = type
    def get_id(self):
        return self._id

    def get_arch(self):
        return self._arch

    def get_layers(self):
        return self._layers

    def get_type(self):
        return self._type

    def get_config_dir(self):
        return self._config_dir

    def get_config_path(self):
        return self._config_path

    def import_from_fs(self, path: str): #FIXME try rsync --delete
        # функция отвечает за копирование файловой системы в образ path - путь до каталога, после которого начинается файловая система
        if os.path.isdir(path):
            _path = Path(path)
            all_copy_items = [item for item in _path.iterdir() if item.name != Image.Config.task_work_dirname]
            for copy_item in all_copy_items:
                if os.path.isdir(copy_item):
                    copy(str(copy_item.absolute()) + '/', os.path.join(self._config_dir, str(copy_item.name)) + '/', with_replace=True)

                else:
                    copy(str(copy_item.absolute()), os.path.join(self._config_dir, str(copy_item.name)), with_replace=True)
                    
                    
            path_hooks = os.path.join(path, Image.Config.task_work_dirname, Image.Config.task_hooks_dirname)
            image_hooks = os.path.join(self._config_dir, Image.Config.task_work_dirname, Image.Config.task_hooks_dirname)
            if path_hooks:
                copy(path_hooks + '/', image_hooks, with_replace=True)

            for ex_item in Image.Config.exclude_list:
                remove(os.path.join(self._config_dir, ex_item))

        else:
            raise Exception("Import path doesn't exist or isn't dir")


    def exist(param, arch=get_machine_arch()) -> bool:
        try:
            Image(param, arch)
            return True
        except:
            return False
    

    def create(self, param=None, arch='multi'): #FIXME create must create new image and return them
        if param is None:
            # FIXME update tree with exists image
            self._type = Image.Type.base

        else:
            parent_image = Image(param)
            if parent_image:
                self._type = Image.Type.simple
                self._layers = parent_image.get_layers()
                self._layers.append(parent_image.fullname)

        
        self.name = read("Enter name of image: ").strip()
        self.author = read("Enter author of image: ").strip()
        self.version = read("Enter version of image: ", default="latest").strip()
        self._arch = arch

        self.fullname = Image.to_fullname(self.author, self.name, self.version)
        if Image.exist(self.fullname, arch=arch):
            raise Exception(f"{self.fullname} already exist")

        self._id = str(uuid.uuid4()).replace("-", "")
        self._config_dir = os.path.join(Image.Config.config_dir, self._id)
        self._config_path = os.path.join(self._config_dir, Image.Config.config_filename)
        self.save()

        return self._id


    def delete(self, dependencies=True):
        if dependencies:
            for image in Image.list():
                if self._id in image.get_layers():
                    image.delete()

        if os.path.exists(self._config_dir):
            remove(self._config_dir)



    def info(self) -> dict:
        data = dict()
        if os.path.isfile(self._config_path):
            data = toml.load(self._config_path)

        else:
            data["image"] = dict()


        data["image"]["name"] = self.name
        data["image"]["author"] = self.author
        data["image"]["version"] = self.version

        data["image"]["id"] = self.get_id()
        data["image"]["type"] = self.get_type()
        data["image"]["layers"] = self.get_layers()
        data["image"]["arch"] = self.get_arch()

        return data


    def save(self, is_base_image=False):
        data = self.info()

        os.makedirs(self._config_dir, exist_ok=True)
        with open(self._config_path, "w") as f:
            toml.dump(data, f)

        if is_base_image:
            copy(os.getcwd(), self._config_dir + '/', progress_bar=True)


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


    def to_fullname(*args) -> str:
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


    def get_manifest(param, arch=get_machine_arch()) -> dict:
        if isinstance(param, str):
            if '/' in param:
                author, name, version = Image._parse_fullname(param)
                for file in glob.glob(Image.Config.config_dir + "/**/" + Image.Config.config_filename, recursive=False):
                    temp = toml.load(file)
                    if temp['image']['name'] == name and temp['image']['version'] == version and temp['image']['author'] == author:
                        if 'arch' not in temp['image'] or temp['image']['arch'] == 'multi' or temp['image']['arch'] == arch:
                            return temp

            else:
                id = param
                for file in glob.glob(Image.Config.config_dir + "/**/" + Image.Config.config_filename, recursive=False):
                    temp = toml.load(file)

                    if temp['image']['id'] == id:
                        return temp

        elif Image.check_manifest(param):
            return param

        raise Exception(' '.join(["Can't find image", str(param), f"arch=multi|{arch}", "locally"]))


    def get_fullname(param) -> str|None:
        try:
            return Image(param).fullname
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

        table = [["ID", "NAME", "TYPE", "PARENT IMAGE", "ARCH"]]

        for manifest in manifests:
            arch = "multi"
            if "arch" in manifest["image"]:
                arch = manifest["image"]["arch"]

            parent_image_name = None
            if manifest["image"]["layers"]:
                parent_image_name = manifest["image"]["layers"][-1]

            table.append([manifest["image"]["id"][:16]
                            , Image.get_fullname(manifest)
                            , manifest["image"]["type"]
                            , parent_image_name
                            , arch])

        print(tabulate(table, headers="firstrow", tablefmt="grid"))


    def load_task_config(self, path: str):
        if self._type == Image.Type.task:
            _ = toml.load(path) # test toml via load
            copy(path, os.path.join(self._config_dir, Image.Config.task_config_dirname, Image.Config.task_config_filename))

        else:
            raise Exception(' '.join(["Image id =", self._id, "is not task image"]))


    def load_task_hooks(self, path: str):
        hooks_dir = os.path.join(self._config_dir, Image.Config.task_work_dirname, Image.Config.task_hooks_dirname)
        copy(path + '/', hooks_dir + '/', with_replace=True)
