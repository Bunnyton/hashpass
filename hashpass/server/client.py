import os
import subprocess
import requests
import json
from pathlib import Path

from threading import Thread
from tabulate import tabulate

from ..utils import remove
from ..core.image import Image

from ..settings import Settings
from ..userconfig import UserConfig



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


    def get_info(self, param: str):
        if not self.check_connection():
            raise Exception("Can't connect to server")
            
        data = {'param': param}
        response = requests.post(f"{self.server_url}/info", data=data)
        if response.status_code != 200:
            return None

        return response.json()


    def _pull(self, image_id: str, force=False):
        config_dir = os.path.join(Image.Config.config_dir, image_id)
        os.makedirs(config_dir, exist_ok=True)
        archive_path = os.path.join(config_dir, f"{image_id}.tar.gz")
        try:
            if Image.get(image_id):
                return

            _path = Path(config_dir)
            if len(list(_path.iterdir())) > 1:
                error_text = f"Directory {config_dir} is not empty"
                if force:
                    print(error_text)
                    print(f"Force option is enabled -> remove {config_dir}")
                    remove(config_dir)

                else:
                    raise Exception(error_text)

            archive_response = requests.get(f"{self.server_url}/download/{image_id}", stream=True)
            if archive_response.status_code != 200:
                raise Exception(f"Download image error: {archive_response.text}")

            os.makedirs(config_dir, exist_ok=True)

            with open(archive_path, "wb") as f:
                f.write(archive_response.content)

            subprocess.run(["tar", "--extract", "--gzip", "--preserve-permissions"
                                                        , "--file", archive_path
                                                        , "--directory", config_dir], check=True,)

        except Exception:
            raise 

        finally:
            remove(archive_path)
                

    def _push(self, image_id: str, force=False):
        archive_path = os.path.join(Image.Config.config_dir, image_id + '.tar.gz')
        try:
            if not force and self.get_info(image_id):
                raise Exception(f"Image already exist on registry")

            else:
                image = Image(image_id)
                manifest = image.info()
                flags = {"force": force}

                
                subprocess.run(["tar", "--create", "--gzip", "--preserve-permissions"
                                                           , "--file", archive_path
                                                           , "--directory", image.config_dir, '.'], check=True,)

                with open(archive_path, "rb") as f:
                    files = {
                        'image': f,
                    }
                    data = {
                        'manifest': json.dumps(manifest),
                        'flags': json.dumps(flags)
                    }
                    return requests.post(f"{self.server_url}/push", files=files, data=data, stream=True)

        except Exception:
            raise

        finally:
            remove(archive_path)


    def push(self, param: str, force=False):
        try:
            if not self.check_connection():
                raise Exception("Can't connect to server")

            if not force and self.get_info(param):
                raise Exception(f"{param} already exist on registry")

            else:
                image = Image(param)

                errors = {}
                thrs: [str, Thread] = {}

                def worker(_image_id: str, _force=False):
                    try:
                        self._push(_image_id, _force)

                    except Exception as e:
                        errors[_image_id] = e

                for image_layer_id in image.layers:
                    if not self.get_info(image_layer_id):
                        print(f"Pushing image: {image_layer_id}")

                        thr = Thread(target=worker, args=(image_layer_id,))
                        thr.start()
                        thrs[image_layer_id] = thr


                print(f"Pushing image: {param}")

                thr = Thread(target=worker, args=(image.id, force,))
                thr.start()
                thrs[image.id] = thr

                for image_id, thr in thrs.items():
                    thr.join()
                    if image_id in errors:
                        raise errors[image_id]

                    else:
                        print(f"{image_id} ✅")

        except Exception as e:
            raise Exception("Push error: " + str(e))


    def pull(self, param: str = None, force=False):
        try:
            if not param:
                raise Exception(f"Image with name {param} can't be exist")

            if Image.get(param):
                # raise Exception(f"{param} already pulled")
                print(f"{param} already pulled")
                return

            if not self.check_connection():
                raise Exception("Can't connect to server")

            manifest = self.get_info(param)
            if manifest is None:
                raise Exception(f"Image {param} not found on registry")


            errors = {}
            thrs: dict[str, Thread] = {}

            def worker(image_id: str):
                try:
                    self._pull(image_id, force)

                except Exception as e:
                    print(e)
                    errors[image_id] = e


            for layer_image_id in manifest["image"]["layers"]:
                if Image.get(layer_image_id):
                    print(f"{layer_image_id} ✅")

                else:
                    print(f"Pulling image: {layer_image_id}")

                    thr = Thread(target=worker, args=(layer_image_id,))
                    thr.start()
                    thrs[layer_image_id] = thr


            print(f"Pulling image: {param}")

            thr = Thread(target=worker, args=(manifest["image"]["id"],))
            thr.start()
            thrs[param] = thr

            for image_id, thr in thrs.items():
                thr.join()
                if image_id in errors:
                    raise errors[image_id]

                else:
                    print(f"{image_id} ✅")

        except Exception as e:
            raise Exception("Pull error: " + str(e))


    def print_remote_images(self):
        try:
            if not self.check_connection():
                raise Exception("Can't connect to server")

            response = requests.get(f"{self.server_url}/images")
            if response.status_code != 200:
                raise Exception(f"Ошибка: {response.text}")

            images = response.json()

            print("Список образов в registry:")
            table = [["ID", "NAME", "TYPE", "PARENT IMAGE ID"]]
            for img in images:
                parent_image_id = None
                if img["image"]["layers"]:
                    parent_image_id = img["image"]["layers"][-1]

                table.append([img["image"]["id"]
                              , Image._to_fullname(img["image"]["author"], img["image"]["name"], img["image"]["version"])
                              , img["image"]["type"], parent_image_id])

            print(tabulate(table, headers="firstrow", tablefmt="grid"))

        except Exception as e:
            raise Exception("Can't get info from server: ", str(e))


    def send_statistic(self):
        try:
            if not self.check_connection():
                raise Exception("Can't connect to server")

            userconfig = UserConfig()
            return requests.post(f"{self.server_url}/student/confirmed", data={"user": userconfig.username, "last_task": task_num})

        except Exception as e:
            raise Exception("Send statistic error: " + str(e))

