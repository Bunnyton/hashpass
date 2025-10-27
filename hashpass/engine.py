import os
import argparse

from hashpass.utils import get_machine_arch
from hashpass.server import Client
from hashpass.core import Image, Container


def print_images():
    Image.print_images()


def info(*args):
    parser = argparse.ArgumentParser(description='hashengine.py info')
    parser.add_argument( '--arch', metavar='ARCH',
                         nargs='?', choices=['amd64', 'arm64', 'multi'],
                         default=get_machine_arch(),
                         help='Architecture of image')
    parser.add_argument('images', nargs='*', help="info's images")
    pargs = parser.parse_args(args)

    images_info = list()
    for image in pargs.images:
        images_info.append(Image.get_manifest(image, arch=pargs.arch))

    Image.print_images(*images_info)


def new(*args):
    parser = argparse.ArgumentParser(description='hashengine.py new make a new base image from fs in current directory')
    parser.add_argument( '--arch', metavar='ARCH',
                         choices=['amd64', 'arm64', 'multi'],
                         help='Architecture of new base image')
    pargs = parser.parse_args(args)
    image = Image()
    image.create(arch=pargs.arch)
    image.import_from_fs(os.getcwd())
    print(image.get_id())


def pull(*args):
    parser = argparse.ArgumentParser(description='hashengine.py pull')
    parser.add_argument('-a', '--all', action='store_true',
                        help='pull all images from registry')
    parser.add_argument('-l', '--layers', action='store_true',
                        help='pull all layers with update from registry')
    parser.add_argument( '--arch', metavar='ARCH',
                         nargs='?', choices=['amd64', 'arm64', 'multi'],
                         default=get_machine_arch(),
                         help='Architecture of pulling image')
    parser.add_argument('images', nargs='*', help='to pull images')
    pargs = parser.parse_args(args)

    client = Client()
    if len(pargs.images) == 0 and not pargs.all:
        Image.print_images(*client.get_remote_images())

    elif pargs.all:
        images = set()
        for image in client.get_remote_images():
            images.add(Image.to_fullname(image))
        client.pull(*images, pull_layers=True, arch=pargs.arch)

    else:
        client.pull(*pargs.images, pull_layers=True, arch=pargs.arch)


def push(*args):
    parser = argparse.ArgumentParser(description='hashengine.py push')
    parser.add_argument('-f', '--force', action='store_true',
                        help='replace image layers on registry')
    parser.add_argument('-a', '--all', action='store_true',
                        help='push all images to registry')
    parser.add_argument('-i', '--ignore', action='store_true',
                        help='ignore errors')
    parser.add_argument( '--arch', metavar='ARCH',
                                        nargs='?', choices=['amd64', 'arm64', 'multi'],
                                        default='multi',
                                        help='Architecture of pushing image')
    parser.add_argument('images', nargs='*', help='to push image layers')
    pargs = parser.parse_args(args)

    if pargs.force:
        ans = input("This command replace image layer on registry, you are sure? [y] ")
        if 'y' != ans.strip().lower():
            return

    client = Client()
    if pargs.images:
        for image_name in pargs.images:
            try:
                client.push(image_name, force=pargs.force, arch=pargs.arch)
            except Exception as e:
                if pargs.ignore:
                    print(e)
                else:
                    raise

    elif pargs.all:
        images = Image.list()
        for image in images:
            try:
                client.push(image.get_id(), force=pargs.force, arch=pargs.arch)
            except Exception as e:
                if pargs.ignore:
                    print(str(e) + '❌')
                else:
                    raise


def send_statistic(*args):
    client = Client()

    if len(args) == 0:
        client.send_statistics()

    else:
        raise Exception("Function send_statistics() hasn't any args")



def delete(*args):
    parser = argparse.ArgumentParser(description='hashengine.py delete')
    parser.add_argument('-f', '--force', action='store_true',
                        help='delete without questions for every image')
    parser.add_argument('-a', '--all', action='store_true',
                        help='delete all local images')
    parser.add_argument('--arch', metavar='ARCH',
                        choices=['amd64', 'arm64', 'multi'],
                        default=get_machine_arch(),
                        help='Architecture of image')
    parser.add_argument('images', nargs='*', help='to delete image')
    pargs = parser.parse_args(args)

    if pargs.force:
        ans = input(f"This command force delete all dependecies images too, you are sure? [y] ")
        if 'y' != ans.strip().lower():
            return

    images = pargs.images
    if len(images) == 0:
        if pargs.all:
            images = Image.list()
        else:
            raise Exception("Image to delete not found")

    for _image in images:
        try:
            if isinstance(_image, Image):
                image = _image
            else:
                image = Image(_image, arch=pargs.arch)

            if not pargs.force:
                ans = input(f"This command delete all dependecies image of {image.fullname} too, you are sure? [y] ")
                if 'y' != ans.strip().lower():
                    print(f"❌ Cancel deleting of {image.fullname}")
                    continue

            print(f"Deleting {image.fullname}")
            image.delete()
            print(f"✅ Delete {image.fullname} successfull")

        except Exception as e:
            print(' '.join(['❌' , str(e)]))


def edit(*args):
    parser = argparse.ArgumentParser(description='hashengine.py edit')
    parser.add_argument('image', help='image for editing')
    parser.add_argument('--arch', metavar='ARCH',
                                            choices=['amd64', 'arm64', 'multi'],
                                            default=get_machine_arch(),
                                            help='Architecture of image')
    pargs = parser.parse_args(args)

    image = Image(pargs.image, arch=pargs.arch)
    container = Container(image)
    container.start(mode=Container.Mode.edit)


def play(*args):
    parser = argparse.ArgumentParser(description='hashengine.py play')
    parser.add_argument('image', help='task (image) for playing')
    parser.add_argument('--arch', metavar='ARCH',
                                            choices=['amd64', 'arm64', 'multi'],
                                            default=get_machine_arch(),
                                            help='Architecture of image')
    pargs = parser.parse_args(args)

    image: Image
    try:
        image = Image(pargs.image, arch=pargs.arch)

    except Exception as e:
        pull(args)
        image = Image(pargs.image, arch=pargs.arch)

    container = Container(image)
    container.start(mode=Container.Mode.task_play)


def create(*args):
    parser = argparse.ArgumentParser(description='hashengine.py create')
    parser.add_argument('-f', '-p', '--from', '--parent', help='parent image') #FIXME
    parser.add_argument('--arch', metavar='ARCH',
                                            choices=['amd64', 'arm64', 'multi'],
                                            default='multi',
                                            help='Architecture of image')
    pargs = parser.parse_args(args)

    image = Image()
    image.create(pargs.parent, arch=pargs.arch)

    container = Container(image)
    container.start(mode=Container.Mode.task_create)


def remote(*args):
    parser = argparse.ArgumentParser(description='hashengine.py remote')
    parser.add_argument('cmd', choices=['remove', 'info'], help='delete or info image from registry')
    parser.add_argument('--arch', metavar='ARCH',
                        choices=['amd64', 'arm64', 'multi'],
                        default=get_machine_arch(),
                        help='Architecture of image on registry')
    parser.add_argument('images', nargs='*', help='image to remove or info from registry')
    pargs = parser.parse_args(args)

    client = Client()
    if pargs.cmd == 'remove':
        ans = input("This command remove image layer only, you are sure? [y] ")
        if 'y' != ans.strip().lower():
            return

        for image in pargs.images:
            client.remote_remove(image, arch=pargs.arch)

    elif len(pargs.images) == 0:
        client.print_remote_images()

    else:
        manifests = list()
        for image in pargs.images:
            manifest = client.get_info(image, arch=pargs.arch)
            if manifest is None:
                raise Exception(f"Image {image} arch=multi|{pargs.arch} not found on registry")
            else:
                manifests.append(manifest)

        Image.print_images(*manifests)


# def rename(*args):
        #     try:
        #         _ = Image(sys.argv[3])

        #     except Exception:
        #         image = Image(sys.argv[2])

        #         new_image_id = str(uuid.uuid4()).replace("-", "")
        #         move(os.path.join(Image.Config.config_dir, image.id), os.path.join(Image.Config.config_dir, new_image_id))

        #         image.author, image.name, image.version = Image._parse_fullname(sys.argv[3])
        #         image.id = new_image_id
        #         image.save()

        #         print(f"Rename {sys.argv[2]} to {sys.argv[3]} successfull")

        #     else:
        #         raise Exception(f"Image {sys.argv[3]} already exist")


