# Пакеты: flatpak

Образец org.example.Hello уже собран в ~/flatpak: заглянуть в его metadata и files/, потом по нему
собрать pelmeni.flatpak — metadata, flatpak build-finish → build-export → build-bundle. Запустить
flatpak в консоли нельзя — проверка достаёт приложение из бандла и запускает его, подставив /app.
