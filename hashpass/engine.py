import sys
import os
import argparse

from .server import Client
from .core import Image, Container


def print_images():
    Image.print_list()


def new(*args):
    if len(args) == 0:
        image = Image()
        image.create()
        image.import_from_fs(os.getcwd())
        print(image.id)

    else:
        raise Exception("Function new() hasn't any args")


def pull(*args):
    parser = argparse.ArgumentParser(description='hashengine.py pull')
    parser.add_argument('-a', '--all', action='store_true',
                        help='pull all images from registry')
    parser.add_argument('images', nargs='*', help='to pull images')
    pargs = parser.parse_args(args)

    client = Client()
    if len(pargs.images) == 0:
        if pargs.all:
            remote_images = client.get_remote_images()
            client.pull(*remote_images, force=True)

        else:
            client.print_remote_images()

    elif len(pargs.images) > 0:
        client.pull(*pargs.images, force=True)


def push(*args):
    parser = argparse.ArgumentParser(description='hashengine.py push')
    parser.add_argument('-f', '--force', action='store_true',
                        help='replace image layers on registry')
    parser.add_argument('images', nargs='*', help='to push image layers')
    pargs = parser.parse_args(args)

    if pargs.force:
        ans = input("This command replace image layer on registry, you are sure? [y] ")
        if 'y' != ans.strip().lower():
            return

    client = Client()
    if pargs.images:
        for image_name in pargs.images:
            client.push(image_name, force=pargs.force)

    else:
        raise Exception("Function push() must has one or more args")


def send_statistic(*args):
    client = Client()

    if len(args) == 0:
        client.send_statistics()

    else:
        raise Exception("Function send_statistics() hasn't any args")



def delete(*args):
    if len(args) > 0:
        ans = input("This command remove all dependecies image, you are sure? [y] ")
        if 'y' != ans.strip().lower():
            return

        for image_id in args:
            try:
                image = Image(image_id)
                image.delete()

            except Exception as e:
                print(' '.join(['❌' , str(e)]))

    else:
        raise Exception("Function remove() must has one or more args")


def edit(*args):
    if len(args) == 1:
        image = Image(args[0])
        container = Container(image)
        container.start(mode=Container.Mode.edit)

    else:
        raise Exception("Function edit() must has only one arg")


def play(*args):
    if len(args) == 1:
        image: Image
        try:
            image = Image(args[0])

        except Exception as e:
            pull(args[0])
            image = Image(args[0])
            
        container = Container(image)
        container.start(mode=Container.Mode.task_play)

    else:
        raise Exception("Function play() must has only one arg")


def create(*args):
    if len(args) == 1:
        image = Image()
        image.create(args[0])

        container = Container(image)
        container.start(mode=Container.Mode.task_create)

    else:
        raise Exception("Function play() must has only one arg")


def remote(*args):
    if len(args) > 1:
        if args[0] in ['remove', 'rm', 'delete', 'del']:
            client = Client()

            ans = input("This command remove image layer only, you are sure? [y] ")
            if 'y' != ans.strip().lower():
                return

            for image_name in args[1::]:
                client.remove(image_name)

    else:
        raise Exception("Function remote() must has more one arg")



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


