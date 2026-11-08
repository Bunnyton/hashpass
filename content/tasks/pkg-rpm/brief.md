# Пакет .rpm

В Fedora, RHEL, CentOS, openSUSE пакеты — `.rpm`. Внутри то же, что в `.deb` — файлы и
паспорт, — а рецепт сборки один файл: **spec**. Собирает `rpmbuild`.

`rpmbuild` работает в своём дереве `~/rpmbuild`:

| Каталог | Что там |
|---|---|
| `SOURCES/` | исходники — архивом `имя-версия.tar.gz`, внутри каталог `имя-версия/` |
| `SPECS/` | рецепты `.spec` |
| `RPMS/` | готовые пакеты (`RPMS/noarch/…` для скриптов) |
| `BUILD/`, `BUILDROOT/` | черновики сборки |

spec — заголовок «поле: значение» и разделы-шаги со знака `%`. Пример для `hello-cat`:

```
Name:      hello-cat
Version:   0.3
Release:   1
Summary:   Печатает котика
License:   MIT
BuildArch: noarch
Source0:   %{name}-%{version}.tar.gz

%description
Печатает котика в терминал.

%prep
%setup -q

%install
install -Dm755 hello-cat %{buildroot}%{_bindir}/hello-cat

%files
%{_bindir}/hello-cat
```

- `%prep` — распаковать исходники (`%setup` сам распакует `Source0` и зайдёт внутрь);
- `%install` — разложить файлы в `%{buildroot}` — это будущий корень пакета;
- `%files` — что из `%{buildroot}` войдёт в пакет: **все** файлы, которые там появились.

`%{_bindir}` — это `/usr/bin`, `%{_mandir}` — `/usr/share/man`. Собрать только бинарный пакет:

```sh
rpmbuild -bb ~/rpmbuild/SPECS/hello-cat.spec
```

Исходники pelmeni — в `~/pelmeni`, и в нём есть `Makefile` с целью `install`.
