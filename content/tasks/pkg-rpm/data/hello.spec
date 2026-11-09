Name:      hello
Version:   1.0
Release:   1
Summary:   Здоровается
License:   MIT
BuildArch: noarch
Source0:   %{name}-%{version}.tar.gz

%description
Образец пакета: здоровается с тем, кого назовёшь.

%prep
%setup -q

%install
make install DESTDIR=%{buildroot}

%files
%{_bindir}/hello
