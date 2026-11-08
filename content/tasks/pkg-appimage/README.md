# Пакеты: AppImage

AppDir (AppRun, .desktop, иконка, usr/bin) и appimagetool → Pelmeni-x86_64.AppImage. Во втором
шаге figlet кладётся внутрь (apt download + dpkg -x), а AppRun выставляет PATH и
FIGLET_FONTDIR: AppImage работает там, где figlet нет.
