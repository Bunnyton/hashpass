import subprocess

import requests
import json
import toml
import os

from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event
from threading import Thread

from hashpass.utils import remove, hashsum, get_machine_arch
from hashpass.core.image import Image

from hashpass.userconfig import UserConfig
from hashpass.settings import Settings



class Client():
    server_url: str = None


    def __init__(self):
        settings = Settings()
        self.server_url = settings.server_url


    def check_connection(self, timeout: float = 2.0, verify_tls=False) -> bool:
        try:
            r = requests.head(self.server_url, timeout=timeout, allow_redirects=True, verify=verify_tls)

            if r.status_code == 405:  # Method Not Allowed
                requests.get(self.server_url, timeout=timeout, allow_redirects=True, verify=verify_tls)

            return True  # Любой ответ означает, что порт слушает и отвечает

        except requests.exceptions.SSLError:
            # TCP-порт, скорее всего, открыт (TLS ругается). Считаем «открыт» на уровне TCP.
            return True

        except requests.RequestException:
            # Таймаут, отказ в соединении, DNS и пр. — считаем «закрыт/недоступен»
            return False


    def get_info(self, param: str, arch=get_machine_arch()) -> dict | None:
        if not self.check_connection():
            raise Exception("Can't connect to server")

        data = {'param': param,
                'arch': arch}
        response = requests.post(f"{self.server_url}/info", data=data)
        if response.status_code != 200:
            return None

        return response.json()


    def _pull(self, manifest: dict, arch=get_machine_arch()) -> dict:
        old_image_fullname = manifest["image"]["author"] + '/' + manifest["image"]["name"]
        old_image_fullname += ':' + manifest["image"]["version"]
        old_config_dir = None
        if Image.exist(old_image_fullname, arch=arch):
            old_image_id = Image(old_image_fullname).get_id()
            old_config_dir = os.path.join(Image.Config.config_dir, old_image_id)

        image_id = manifest["image"]["id"]
        config_dir = os.path.join(Image.Config.config_dir, image_id)
        config_path = os.path.join(config_dir, Image.Config.config_filename)
        archive_path = os.path.join(config_dir, f"{image_id}.tar.gz")

        try:
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

            remove(archive_path)
            if old_config_dir:
                remove(old_config_dir)

        except Exception:
            remove(config_dir)
            raise


    def _push(self, image_id: str, force=False, arch="multi"):
        archive_path = os.path.join(Image.Config.config_dir, image_id + '.tar.gz')
        try:
            if not force and self.get_info(image_id, arch=arch):
                raise Exception(f"Image {image_id} arch=multi|{arch} already exist on registry")

            else:
                image = Image(image_id, arch=arch)
                try:
                    manifest = image.info()
                    flags = {"force": force}
                    remove(image.get_config_path())

                    subprocess.run(["tar", "--create", "--gzip", "--preserve-permissions"
                                                               , "--file", archive_path
                                                               , "--directory", image.get_config_dir(), '.'], check=True,)

                    manifest['image']['id'] = hashsum(archive_path)
                    manifest['image']['arch'] = arch

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

                    image.set_id(manifest['image']['id'])
                    image.set_arch(arch)

                finally:
                    image.save()

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
                image = Image(param, arch=arch)

                errors = {}
                thrs: [str, Thread] = {}

                def worker(_param: str, _arch):
                    try:
                        print(f"Pushing image: {_param} arch={_arch}")
                        self._push(Image(_param, arch=_arch).get_id(), force=force, arch=_arch)
                        print(f"Image {_param} arch={_arch} pushed successfully ✅")

                    except Exception as e:
                        errors[_param] = e
                    

                for image_layer in image.get_layers():
                    if not self.get_info(image_layer, arch=get_machine_arch()):
                        thr = Thread(target=worker, args=(image_layer, arch))
                        thr.start()
                        thrs[image_layer] = thr


                for _image, thr in thrs.items():
                    thr.join()
                    if _image in errors:
                        raise errors[_image]

                worker(image.fullname, arch)

                image = Image(image.fullname, arch=arch)
                Image.print_images(image.info())

        except Exception as e:
            raise Exception("Push error: " + str(e))

    
    def get_newest_version(self, param, arch=get_machine_arch()) -> [bool, dict]: # return manifest if newest verion on registry
        if not param:
            raise Exception(f"Image with name {param} can't be exist")

        if not self.check_connection():
            raise Exception("Can't connect to server")

        manifest = self.get_info(param, arch=arch)
        if manifest is None:
            raise Exception(f"Image {param} arch=multi|{arch} not found on registry")

        if not Image.exist(param, arch=arch):
            return True, manifest

        elif manifest["image"]["id"] != Image(param, arch=arch).get_id():
            return True, manifest

        return False, manifest

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from threading import Event

    def pull(self, *params, pull_layers=True, arch=get_machine_arch()):
        """
        Pull images and their layers using thread pool.
        Stops all operations on first error.
        """
        errors = {}
        stop_event = Event()

        def worker(_param: str, _arch: str):
            """Внутренняя задача для пула потоков"""
            if stop_event.is_set():
                return  # если кто-то уже упал, прекращаем работу

            status, manifest = self.get_newest_version(_param, arch=_arch)
            if status:
                print(f"Pulling image: {_param} arch=multi|{_arch}")
                self._pull(manifest)  # здесь может быть длительная операция
                print(f"Image {_param} arch=multi|{_arch} pulled successfully ✅")
            else:
                print(f"{_param} arch=multi|{_arch} ✅")

        try:
            # === 1. Формируем список всех задач ===
            layers = set((
                Image.Config.config_layer_base,
                Image.Config.config_layer_basesettings,
                Image.Config.config_layer_taskcreator,
                Image.Config.config_layer_taskchecker
            ))

            if pull_layers:
                for param in set(params):
                    info = self.get_info(param, arch=get_machine_arch())
                    for layer in info['image']['layers']:
                        full = Image.to_fullname(self.get_info(layer, arch=get_machine_arch()))
                        layers.add(full)

            # === 2. Формируем очередь задач ===
            tasks = list(layers) + list(set(params))

            # === 3. Запуск пула потоков ===
            # Можно указать max_workers = 4 или динамически по CPU
            with ThreadPoolExecutor(max_workers=8) as executor:
                future_to_image = {
                    executor.submit(worker, image_name, arch): image_name
                    for image_name in tasks
                }

                # обрабатываем завершение задач
                for future in as_completed(future_to_image):
                    image = future_to_image[future]
                    try:
                        future.result()
                    except Exception as e:
                        errors[image] = e
                        stop_event.set()  # сигнал остальным потокам
                        # Отменяем все незапущенные/незавершённые
                        for f in future_to_image:
                            f.cancel()
                        raise Exception(f"Pull layer error: {image}: {e}")

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
            return requests.post(f"{self.server_url}/student/confirmed", data={"user": userconfig.username,
                                                                           "task_num": userconfig.get_last_task_num()})

        except Exception as e:
            raise Exception("Send statistic error: " + str(e))

