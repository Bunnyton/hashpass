# Пакеты: .deb руками

Сначала — как устроен настоящий пакет: apt download sl и dpkg-deb -R раскладывают его в каталог с
паспортом DEBIAN/control. Потом свой pelmeni так же — dpkg-deb --build, с зависимостью от figlet, —
и установка через apt.
