import glob
import json
import os

import toml
from flask import Flask, abort, jsonify, request, send_file

app = Flask(__name__)
STORAGE_DIR = "storage"
os.makedirs(STORAGE_DIR, exist_ok=True)


@app.route("/images", methods=["GET"])
def list_images():
    """Список всех образов"""
    images = list()
    for file in glob.glob(STORAGE_DIR + "/**/" + "manifest.toml", recursive=False):
        temp = toml.load(file)
        images.append(temp)

    return jsonify(images)


def get(param: str):
    temp = None
    if "/" in param:
        author, name = param.split("/")
        if ":" in name:
            name, version = name.split(":")

        else:
            version = "latest"

        for file in glob.glob(STORAGE_DIR + "/**/" + "manifest.toml", recursive=False):
            temp = toml.load(file)

            if temp["image"]["name"] == name and temp["image"]["version"] == version and temp["image"]["author"] == author:
                return temp

    else:
        for file in glob.glob(STORAGE_DIR + "/**/" + "manifest.toml", recursive=False):
            temp = toml.load(file)

            if temp["image"]["id"] == param:
                return temp

    return None


@app.route("/push", methods=["POST"])
def push_image():
    manifest_raw = request.form.get("manifest")
    image_file = request.files.get("image")  # получаем список файлов

    if manifest_raw and image_file:
        manifest = json.loads(manifest_raw)
        if manifest["image"]["id"] and manifest["image"]["name"] and manifest["image"]["version"] and "layers" in manifest["image"] and manifest["image"]["author"] and manifest["image"]["type"]:
            image_path = os.path.join(STORAGE_DIR, manifest["image"]["id"])

            os.makedirs(image_path, exist_ok=True)
            with open(os.path.join(image_path, "manifest.toml"), "w") as f:
                toml.dump(manifest, f)

            image_file.save(os.path.join(image_path, manifest["image"]["id"] + ".tar.gz"))
            return f"Image {manifest['image']['author']}/{manifest['image']['name']}:{manifest['image']['version']} uploaded successfully", 200


    return "Invalid format", 400


@app.route("/info", methods=["POST"])
def get_info():
    param = request.form.get("param")
    manifest = get(param)
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

