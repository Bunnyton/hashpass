from flask import Flask, request, send_file, jsonify, abort
import os
import toml
import glob
import json


app = Flask(__name__)
STORAGE_DIR = 'storage'
os.makedirs(STORAGE_DIR, exist_ok=True)


@app.route("/images", methods=["GET"])
def list_images():
    """Список всех образов"""

    images = list()
    for file in glob.glob(STORAGE_DIR + "/**/" + 'manifest.toml', recursive=False):
        temp = toml.load(file)
        images.append(temp)

    return jsonify(images)


def get_from_name(author, name, version):
    for file in glob.glob(STORAGE_DIR + "/**/" + 'manifest.toml', recursive=False):
        temp = toml.load(file)

        if temp['image']['name'] == name and temp['image']['version'] == version and temp['image']['author'] == author:
            return temp

    return None



@app.route("/push", methods=["POST"])
def push_image():
    """Загрузка архива (push)"""

    manifest_raw = request.form.get("manifest")
    image = request.files.get("image")  # получаем список файлов

    if manifest_raw and image:
        manifest = json.loads(manifest_raw)
        if manifest['image']['id'] and manifest['image']['name'] and manifest['image']['version'] and 'layers' in manifest['image'] and manifest['image']['author'] and manifest['image']['type']:
            image_path = os.path.join(STORAGE_DIR, manifest['image']['id'])

            os.makedirs(image_path, exist_ok=True)
            with open(os.path.join(image_path, 'manifest.toml'), 'w') as f:
                toml.dump(manifest, f)
        
            image.save(os.path.join(image_path, manifest['image']['id'] + '.tar.gz'))
            return f"Image {manifest['image']['author']}/{manifest['image']['name']}:{manifest['image']['version']} uploaded successfully", 200


    return "Неверный формат", 400



@app.route("/pull", methods=["POST"])
def pull_image():
    """Скачивание образа и манифеста"""

    fullname = request.form.get("fullname")
    print(fullname)
    author, name = fullname.split('/')
    name, version = name.split(':')

    manifest = get_from_name(author, name, version)

    if manifest:
        archive_path = os.path.join(STORAGE_DIR, manifest['image']['id'], manifest['image']['id'] + '.tar.gz')
        if os.path.isfile(archive_path):
            return jsonify(manifest)

        else:
            os.remove(os.path.join(STORAGE_DIR, manifest['image']['id'], 'manifest.toml'))

    return abort(404, description="Образ или манифест не найден")



@app.route("/download/<image_id>", methods=["GET"])
def download_image(image_id):
    """Отдаёт сам образ (без манифеста)"""
    image_path = os.path.join(STORAGE_DIR, image_id, image_id + '.tar.gz')

    if not os.path.exists(image_path):
        return abort(404, description="образ не найден")

    return send_file(image_path, as_attachment=True)



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

