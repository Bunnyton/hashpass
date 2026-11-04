#!/bin/bash
# Тип каждого файла из ~/broken/inbox — по расширению: «тип: имя».
ext() {
    local name=$1
    if [[ $name == *.* ]]; then
        return "${name##*.}"
    fi
    return "нет"
}

for f in ~/broken/inbox/*; do
    name=$(basename "$f")
    echo "$(ext "$name"): $name"
done
