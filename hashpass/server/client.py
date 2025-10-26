import subprocess
import platform

import requests
import json
import toml
import os

from threading import Thread

from hashpass.utils import remove, hashsum, move
from hashpass.core.image import Image

from hashpass.userconfig import UserConfig
from hashpass.settings import Settings


def get_arch() -> str:
    m = platform.machine() or ""
    m = m.strip().lower()

    # Базовая нормализация самых частых вариантов
    mapping = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "x64":    "amd64",

        "aarch64": "arm64",
        "arm64":   "arm64",
    }
    if m in mapping:
        return mapping[m]

    else:
        raise Exception(f"Exotic arch - {m}")


class Client():
    server_url: str = None


    def __init__(self):
        settings = Settings()
        self.server_url = settings.server_url


    def check_connection(self, timeout: float = 2.0, verify_tls=False) -> bool:
        try:
            r = requests.head(self.server_url, timeout=timeout, allow_redirects=True, verify=verify_tls)

            if r.status_code == 405:  # Method Not Allowed
                r = requests.get(self.server_url, timeout=timeout, allow_redirects=True, verify=verify_tls)

            return True  # Любой ответ означает, что порт слушает и отвечает

        except requests.exceptions.SSLError:
            # TCP-порт, скорее всего, открыт (TLS ругается). Считаем «открыт» на уровне TCP.
            return True

        except requests.RequestException:
            # Таймаут, отказ в соединении, DNS и пр. — считаем «закрыт/недоступен»
            return False


    def get_info(self, param: str, arch=get_arch()) -> str | None:
        if not self.check_connection():
            raise Exception("Can't connect to server")

        data = {'param': param,
                'arch': arch}
        response = requests.post(f"{self.server_url}/info", data=data)
        if response.status_code != 200:
            return None

        return response.json()


    def _pull(self, manifest: dict):
        image_id = manifest["image"]["id"]
        config_dir = os.path.join(Image.Config.config_dir, image_id)
        config_path = os.path.join(config_dir, Image.Config.config_filename)
        archive_path = os.path.join(config_dir, f"{image_id}.tar.gz")

        try:
            move(config_dir, config_dir + "_backup")
            os.makedirs(config_dir, exist_ok=True)

            archive_response = requests.get(f"{self.server_url}/download/{image_id}", stream=True)
            if archive_response.status_code != 200:
                raise Exception(f"Download image error: {archive_response.text}")

            with open(archive_path, "wb") as f:
                f.write(archive_response.content)

            subprocess.run(["tar", "--extract", "--gzip", "--preserve-permissions"
                                                        , "--file", archive_path
                                                        , "--directory", config_dir], check=True,)
            with open(config_path, "w") as f:
                toml.dump(manifest, f)

            remove(config_dir + "_backup")

        except Exception:
            move(config_dir + "_backup", config_dir)
            raise 

        finally:
            remove(archive_path)
                

    def _push(self, image_id: str, force=False, arch="multi"):
        archive_path = os.path.join(Image.Config.config_dir, image_id + '.tar.gz')
        try:
            if not force and self.get_info(image_id, arch=arch):
                raise Exception(f"Image {image_id} arch=multi|{arch} already exist on registry")

            else:
                image = Image(image_id)
                manifest = image.info()
                flags = {"force": force}
                remove(image.config_path)

                subprocess.run(["tar", "--create", "--gzip", "--preserve-permissions"
                                                           , "--file", archive_path
                                                           , "--directory", image.config_dir, '.'], check=True,)

                manifest['image']['hashsum'] = hashsum(archive_path)
                manifest['image']['arch'] = arch
                image.hashsum = manifest['image']['hashsum']
                image.save()

                with open(archive_path, "rb") as f:
                    files = {
                        'image': f,
                    }
                    data = {
                        'manifest': json.dumps(manifest),
                        'flags': json.dumps(flags)
                    }
                    resp = requests.post(f"{self.server_url}/push", files=files, data=data, stream=True)
                    if resp.status_code != 200:
                        raise Exception(resp.text)

        except Exception:
            raise

        finally:
            remove(archive_path)


    def push(self, param: str, force=False, arch="multi"):
        try:
            if not self.check_connection():
                raise Exception("Can't connect to server")

            if not force and self.get_info(param, arch=arch):
                print(f"{param} arch=multi|{arch} already exist on registry")
                return

            else:
                image = Image(param)

                errors = {}
                thrs: [str, Thread] = {}

                def worker(_param: str):
                    try:
                        print(f"Pushing image: {_param} arch={arch}")
                        self._push(Image(_param).id, force=force, arch=arch)
                        print(f"Image {_param} arch={arch} pushed successfully ✅")

                    except Exception as e:
                        errors[_image] = e
                    

                for image_layer in image.layers:
                    if not self.get_info(image_layer, arch=arch):
                        thr = Thread(target=worker, args=(image_layer,))
                        thr.start()
                        thrs[image_layer] = thr


                thr = Thread(target=worker, args=(image.fullname,))
                thr.start()
                thrs[image.fullname] = thr

                for _image, thr in thrs.items():
                    thr.join()
                    if _image in errors:
                        raise errors[_image]

                    else:
                        Image.print_images(Image.get_manifest(_image))

        except Exception as e:
            raise Exception("Push error: " + str(e))

    
    def get_newest_version(self, param, arch=get_arch()) -> [bool, dict]: # return manifest if newest verion on registry
        if not param:
            raise Exception(f"Image with name {param} can't be exist")

        if not self.check_connection():
            raise Exception("Can't connect to server")

        manifest = self.get_info(param, arch=arch)
        if manifest is None:
            raise Exception(f"Image {param} not found on registry")


        if not Image.exist(param): 
            return True, manifest

        elif "hashsum" in manifest["image"] and manifest["image"]["hashsum"] != Image.get_hashsum(param):
            return True, manifest

        return False, manifest


    def pull(self, param, pull_layers=False, arch=get_arch()):
        _param = param
        if Image.check_manifest(_param):
            _param = param["image"]["id"]

        try:
            status, manifest = self.get_newest_version(_param, arch=arch)
            if not status:
                print(f"The newest version of {_param} already pulled")
                if pull_layers:
                    print(f"Checking layers of {_param}")
                else:
                    return

            else:
                print(f"\nThe new version of {_param} has been found on registry")

            errors = {}
            thrs: dict[str, Thread] = {}

            def worker(__param: str):
                try:
                    _status, _manifest = self.get_newest_version(__param, arch=arch)
                    if _status:
                        print(f"Pulling image: {__param} arch=multi|{arch}")
                        self._pull(_manifest)
                        print(f"Image {__param} arch=multi|{arch} pulled successfully ✅")
                    else:
                        print(f"{__param} arch=multi|{arch} ✅")

                except Exception as e:
                    errors[image_id] = e

            layers = [Image.Config.config_layer_base, Image.Config.config_layer_basesettings,
                      Image.Config.config_layer_taskcreator, Image.Config.config_layer_taskchecker]
            layers.extend(manifest["image"]["layers"])
            for layer_image in layers:
                thr = Thread(target=worker, args=(layer_image,))
                thr.start()
                thrs[layer_image] = thr


            if status:
                thr = Thread(target=worker, args=(_param,))
                thr.start()
                thrs[_param] = thr

            for _image, thr in thrs.items():
                thr.join()
                if _image in errors:
                    raise errors[_image]

        except Exception as e:
            raise Exception("Pull error: " + str(e))


    def remote_remove(self, param: str = None, arch="multi"):
        try:
            if not param:
                raise Exception(f"Image with name {param} can't be exist")

            manifest = self.get_info(param, arch=arch)
            if manifest:
                data = {
                    'id': manifest['image']['id']
                }
                resp = requests.post(f"{self.server_url}/remove", data=data)

                if resp.status_code != 200:
                    raise Exception(resp.text)

                else:
                    print(f"✅ Image {param} successfully removed on registry")

            else:
                raise Exception(f"Image with name {param} doesn't exist on registry")


        except Exception as e:
            raise Exception("Remote remove error: " + str(e))


    def get_remote_images(self):
        try:
            if not self.check_connection():
                raise Exception("Can't connect to server")

            response = requests.get(f"{self.server_url}/images")
            if response.status_code != 200:
                raise Exception(f"Ошибка: {response.text}")

            return response.json()

        except Exception as e:
            raise Exception("Can't get info from server: ", str(e))


    def print_remote_images(self):
        images = self.get_remote_images()

        if images:
            print("Список образов в registry:")
            Image.print_images(*images)

        else:
            print("registry пуст")


    def send_statistic(self):
        try:
            if not self.check_connection():
                raise Exception("Can't connect to server")

            userconfig = UserConfig()
            return requests.post(f"{self.server_url}/student/confirmed", data={"user": userconfig.username, "last_task": task_num})

        except Exception as e:
            raise Exception("Send statistic error: " + str(e))




