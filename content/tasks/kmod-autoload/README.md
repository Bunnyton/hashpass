# Модули ядра: автозагрузка

hello становится «системным»: установка в /lib/modules (modules_install или копия + depmod),
загрузка по имени через modprobe, автозагрузка из /etc/modules-load.d с перезапуском учебного
ядра и параметр по умолчанию в /etc/modprobe.d.
