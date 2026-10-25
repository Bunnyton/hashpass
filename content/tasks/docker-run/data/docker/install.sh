#!/bin/sh
# Docker для заданий: пакеты Debian + rootless-демон студента (служба пользователя, запускается
# при загрузке благодаря linger) + сокет по стандартному адресу /var/run/docker.sock, так что
# docker работает и без sudo, и с ним. Образы — из /usr/local/share/hp-docker/images.
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq docker.io docker-cli docker-buildx rootlesskit slirp4netns uidmap fuse-overlayfs \
    dbus-user-session iptables curl >/dev/null
# системный (root) демон не нужен и не поднимется: сеть машины общая с хостом
systemctl disable docker.service docker.socket containerd.service >/dev/null 2>&1
systemctl mask docker.service docker.socket containerd.service >/dev/null 2>&1
grep -q '^student:' /etc/subuid || echo student:100000:65536 >> /etc/subuid
grep -q '^student:' /etc/subgid || echo student:100000:65536 >> /etc/subgid
mkdir -p /var/lib/systemd/linger && touch /var/lib/systemd/linger/student
install -D -m 644 /var/tmp/hp-docker/user/docker.service /etc/systemd/user/docker.service
install -D -m 755 /var/tmp/hp-docker/bin/load-images /usr/local/lib/hp-docker/load-images
install -D -m 755 /var/tmp/hp-docker/bin/runc /usr/local/lib/hp-docker/bin/runc
mkdir -p /home/student/.config/systemd/user/default.target.wants
ln -sf /etc/systemd/user/docker.service /home/student/.config/systemd/user/default.target.wants/docker.service
# Консоль запрещает keyctl (связки ключей не разделены между контейнерами и хостом), а runc по
# умолчанию заводит каждому контейнеру свою связку — отключаем это в рантайме демона.
install -D -m 644 /var/tmp/hp-docker/daemon.json /home/student/.config/docker/daemon.json
chown -R student:student /home/student/.config
install -D -m 644 /var/tmp/hp-docker/system/hp-docker-host.service /etc/systemd/system/hp-docker-host.service
systemctl enable hp-docker-host.service >/dev/null 2>&1
mkdir -p /usr/local/share/hp-docker/images
cp /var/tmp/hp-docker/images/*.tar.gz /usr/local/share/hp-docker/images/
rm -rf /var/tmp/hp-docker
