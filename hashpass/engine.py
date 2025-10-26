import os
import argparse

from hashpass.server import Client
from hashpass.core import Image, Container


def print_images():
    Image.print_images()


def new(*args):
    parser = argparse.ArgumentParser(description='hashengine.py new make a new base image from fs in current directory')
    parser.add_argument( '--arch', metavar='ARCH',
                         nargs='?', choices=['amd64', 'arm64', 'multi'],
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
                         help='Architecture of pulling image')
    parser.add_argument('images', nargs='*', help='to pull images')
    pargs = parser.parse_args(args)

    client = Client()

    images = list()
    if len(pargs.images) == 0:
        if pargs.all:
            images = client.get_remote_images()
        else:
            client.print_remote_images()

    elif len(pargs.images) > 0:
        images = pargs.images

    for image in images:
        if pargs.arch:
            client.pull(image, pull_layers=pargs.layers, arch=pargs.arch)
        else:
            client.pull(image, pull_layers=pargs.layers)


def push(*args):
    parser = argparse.ArgumentParser(description='hashengine.py push')
    parser.add_argument('-f', '--force', action='store_true',
                        help='replace image layers on registry')
    parser.add_argument('-a', '--all', action='store_true',
                        help='push all images to registry')
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
                print(e)

    elif pargs.all:
        images = Image.list()
        for image in images:
            client.push(image.id, force=pargs.force, arch=pargs.arch)

    else:
        raise Exception("Function push() must has one or more args")


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
                        nargs=1,  choices=['amd64', 'arm64', 'multi'],
                        default='multi',
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

            image.delete()

        except Exception as e:
            print(' '.join(['❌' , str(e)]))


def edit(*args):
    parser = argparse.ArgumentParser(description='hashengine.py edit')
    parser.add_argument('image', nargs=1,
                        help='image for editing')
    parser.add_argument('--arch', metavar='ARCH',
                        nargs=1,  choices=['amd64', 'arm64', 'multi'],
                        default='multi',
                        help='Architecture of image')
    pargs = parser.parse_args(args)

    image = Image(pargs.image, arch=pargs.arch)
    container = Container(image)
    container.start(mode=Container.Mode.edit)


def play(*args):
    parser = argparse.ArgumentParser(description='hashengine.py play')
    parser.add_argument('image', nargs=1,
                        help='task (image) for playing')
    parser.add_argument('--arch', metavar='ARCH',
                        nargs=1,  choices=['amd64', 'arm64', 'multi'],
                        default='multi',
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
    parser.add_argument('-f', '-p', '--from', '--parent', nargs=1,
                        help='parent image') #FIXME
    parser.add_argument('--arch', metavar='ARCH',
                        nargs=1,  choices=['amd64', 'arm64', 'multi'],
                        default='multi',
                        help='Architecture of image')
    pargs = parser.parse_args(args)

    image = Image()
    image.create(pargs.parent, arch=pargs.arch)

    container = Container(image)
    container.start(mode=Container.Mode.task_create)


def remote(*args):
    parser = argparse.ArgumentParser(description='hashengine.py remote')
    parser.add_argument('remove', nargs=1, choices=['remove'], help='delete image from registry')
    parser.add_argument('--arch', metavar='ARCH',
                        nargs=1,  choices=['amd64', 'arm64', 'multi'],
                        default='multi',
                        help='Architecture of remote removing image')
    pargs = parser.parse_args(args)

    client = Client()
    ans = input("This command remove image layer only, you are sure? [y] ")
    if 'y' != ans.strip().lower():
        return

    for image_name in args[1::]:
        client.remote_remove(image_name, arch=pargs.arch)



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


