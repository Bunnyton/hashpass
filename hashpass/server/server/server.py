import os
import glob
import json
import shutil
import toml

from functools import wraps
from db_module import DBConnector


from flask import Flask, abort, jsonify, request, send_file

app = Flask(__name__)

STORAGE_DIR = 'storage'
DATABASE_CONNECTOR = DBConnector(os.path.join(STORAGE_DIR, "students.sqlite"))

os.makedirs(STORAGE_DIR, exist_ok=True)


def ip_validation(f):
    @wraps(f)
    def decorator(*args, **kwargs):
        if not request.remote_addr in ["127.0.0.1", "195.19.37.169", "10.10.1.229"]: # Localhost и белый IP 408
            return abort(404, description="Invalid IP")
        return f(*args, **kwargs)
    return decorator


@app.route("/images", methods=["GET"])
def list_images():
    """Список всех образов"""
    images = list()
    for file in glob.glob(STORAGE_DIR + "/**/" + "manifest.toml", recursive=False):
        temp = toml.load(file)
        images.append(temp)

    return jsonify(images)


def get(param: str, arch="multi"):
    if "/" in param:
        author, name = param.split("/")
        if ":" in name:
            name, version = name.split(":")
        else:
            version = "latest"

        for file in glob.glob(STORAGE_DIR + "/**/" + "manifest.toml", recursive=False):
            temp = toml.load(file)

            if temp["image"]["name"] == name and temp["image"]["version"] == version and temp["image"]["author"] == author:
                if arch not in temp["image"] or temp["image"]["arch"] == "multi" or temp["image"]["arch"] == arch:
                    return temp

    else:
        for file in glob.glob(STORAGE_DIR + "/**/" + "manifest.toml", recursive=False):
            temp = toml.load(file)

            if temp["image"]["id"] == param:
                return temp

    return None


def check_flag(flags_raw, flag: str):
    if flags_raw:
        flags = json.loads(flags_raw)
        if flag in flags and flags[flag]:
            return True

    return False


def remove(image_id: str):
    image_path = os.path.join(STORAGE_DIR, image_id)
    if os.path.exists(image_path):
        shutil.rmtree(image_path)


@app.route("/remove", methods=["POST"])
def remove_image():
    id = request.form.get("id")
    if id:
        if get(id):
            remove(id)
            return f"Image {id} removed successfully", 200

        else:
            return f"Image {id} doesn't exist", 500

    return "Invalid format", 400





@app.route("/push", methods=["POST"])
def push_image():
    manifest_raw = request.form.get("manifest")
    flags_raw = request.form.get("flags")
    image_file = request.files.get("image")  # получаем список файлов


    if manifest_raw and image_file:
        manifest = json.loads(manifest_raw)
        if manifest["image"]["id"] and manifest["image"]["name"] and manifest["image"]["version"]:
            if "layers" in manifest["image"] and manifest["image"]["author"] and manifest["image"]["type"]:
                image_path = os.path.join(STORAGE_DIR, manifest["image"]["id"])

                fullname = manifest["image"]["author"] + '/' + manifest["image"]["name"]
                fullname += ':' + manifest["image"]["version"]
                image_old_manifest = get(fullname, arch=manifest["image"]["arch"])

                if get(image_old_manifest["image"]["id"]):
                    if check_flag(flags_raw, "force"):
                        remove(image_old_manifest["image"]["id"])
                    else:
                        return f"Image {manifest["image"]["id"]} already exist", 500

                os.makedirs(image_path, exist_ok=True)

                image_file.save(os.path.join(image_path, manifest["image"]["id"] + ".tar.gz"))
                with open(os.path.join(image_path, "manifest.toml"), "w") as f:
                    toml.dump(manifest, f)

                return f"Image {manifest['image']['author']}/{manifest['image']['name']}:{manifest['image']['version']} uploaded successfully", 200


    return "Invalid format", 400


@app.route("/info", methods=["POST"])
def get_info():
    param = request.form.get("param")
    arch = request.form.get("arch")
    manifest = get(param, arch=arch)
    if not manifest:
        return abort(404, description="Image not found")

    else:
        return jsonify(manifest)


@app.route("/download/<image_id>", methods=["GET"])
def download_image(image_id):
    """Отдаёт сам образ (без манифеста)"""
    image_path = os.path.join(STORAGE_DIR, image_id, image_id + ".tar.gz")

    if not os.path.exists(image_path):
        return abort(404, description="Image not found")

    return send_file(image_path, as_attachment=True)


@app.route("/student/confirmed", methods=["POST"])
def task_confirmation():
    username: str = request.form.get("user", "")
    if not username:
        return abort(404, description="Username not provided")

    # Валидация номера задания
    task_number_str = request.form.get("last_task", None)
    task_number: int = int(task_number_str) if (isinstance(task_number_str, int) or (isinstance(task_number_str, str) and task_number_str.isdigit())) else None
    if task_number == None:
        return abort(404, description="Task not provided")
    if not DATABASE_CONNECTOR.add_record(username=username, task_number=task_number, ip_address=request.remote_addr):
        return abort(404, description="DB Err!")
    return "Ok"


@app.route("/student/info/short", methods=["GET"])
@ip_validation
def get_student_info_short():
    return DATABASE_CONNECTOR.get_students_score_short()


@app.route("/student/info/long", methods=["GET"])
@ip_validation
def get_student_info_long():
    return DATABASE_CONNECTOR.get_students_score_detailed()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

