# Пакеты: .rpm

Дерево ~/rpmbuild, тарбол pelmeni-1.0.tar.gz и spec: %prep/%install/%files → noarch.rpm через
rpmbuild. Затем Requires: figlet и %changelog в версии 1.1. Проверка — rpm -qp.
