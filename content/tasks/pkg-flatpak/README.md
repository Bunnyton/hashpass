# Пакеты: flatpak

metadata, files/ и flatpak build-finish → build-export → build-bundle — так flatpak-builder
упаковывает приложение в конце. Во втором шаге figlet кладётся внутрь, а шрифты указываются через
[Environment]. Запустить flatpak в консоли нельзя — проверка достаёт приложение из бандла и
запускает его, подставив /app.
