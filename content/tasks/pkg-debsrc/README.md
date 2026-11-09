# Пакеты: исходный пакет Debian

Сначала — исходники настоящего пакета (apt-get source sl) и его debian/rules: вся сборка — dh $@.
Потом то же для своей программы: заготовка debian/ через dh_make и пакет через dpkg-buildpackage.
