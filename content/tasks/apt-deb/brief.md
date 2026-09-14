# .deb: установка «руками»

Все пакеты в Debian/Ubuntu — это `.deb`-файлы. По сути архив с:

- контрольной информацией (зависимости, версия);
- скриптами установки/удаления;
- собственно файлами.

Установить из готового `.deb`:

    sudo dpkg -i пакет.deb
    # или новее:
    sudo apt install ./пакет.deb

## Задание

Скачайте пакет **cmatrix** и попробуйте установить его вручную:

    wget http://ftp.debian.org/debian/pool/main/c/cmatrix/cmatrix_2.0-3_amd64.deb
    sudo dpkg -i cmatrix_2.0-3_amd64.deb

Just Google it!

> Не запускайте `cmatrix` заранее — сюрприз пропадёт.

Нажмите **Enter**.
