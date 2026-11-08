---
tags: пакеты, rpm, rpmbuild, spec, fedora
---
# .rpm и spec

RPM — формат Red Hat: Fedora, RHEL, CentOS Stream, AlmaLinux, Rocky, openSUSE. Рецепт — файл
`.spec`, сборка — `rpmbuild` в дереве `~/rpmbuild`.

    ~/rpmbuild/SOURCES/hello-cat-0.3.tar.gz
    ~/rpmbuild/SPECS/hello-cat.spec
    ~/rpmbuild/RPMS/noarch/hello-cat-0.3-1.noarch.rpm   ← результат

## Разделы spec

| Раздел | Что делает |
|---|---|
| заголовок | `Name`, `Version`, `Release`, `Summary`, `License`, `Source0`, `Requires`, `BuildRequires` |
| `%description` | длинное описание |
| `%prep` | распаковать (`%setup -q`), наложить патчи |
| `%build` | собрать (`%make_build`) |
| `%install` | разложить в `%{buildroot}` (`%make_install`) |
| `%files` | что из buildroot войдёт в пакет; `%doc`, `%license`, `%config` |
| `%changelog` | `* Mon Nov 09 2026 Имя <почта> - 0.3-1` |

Макросы путей: `%{_bindir}` = `/usr/bin`, `%{_mandir}` = `/usr/share/man`, `%{_datadir}` =
`/usr/share`. Посмотреть любой: `rpm --eval '%{_bindir}'`.

## Команды

    $ rpmbuild -bb hello-cat.spec      # только бинарный пакет
    $ rpmbuild -ba hello-cat.spec      # + исходный .src.rpm
    $ rpm -qpi файл.rpm                # паспорт
    $ rpm -qpl файл.rpm                # файлы
    $ rpm -qp --requires файл.rpm      # зависимости
    $ sudo dnf install ./файл.rpm      # на Fedora — с зависимостями

## .deb и .rpm

| | Debian | RPM |
|---|---|---|
| рецепт | `debian/` (несколько файлов) | один `.spec` |
| сборка | `dpkg-buildpackage` | `rpmbuild` |
| версия | `1.0-1` в changelog | `Version` + `Release` |
| зависимости | `Depends` | `Requires` |
| проверка | `lintian` | `rpmlint` |
| поставить | `apt install ./x.deb` | `dnf install ./x.rpm` |

## Источники

- [RPM Packaging Guide](https://rpm-packaging-guide.github.io/)
- [Fedora Packaging Guidelines](https://docs.fedoraproject.org/en-US/packaging-guidelines/)
