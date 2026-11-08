# copyright

В Debian каждый пакет обязан сказать, на каких условиях его можно распространять: файл
`debian/copyright` попадает в `/usr/share/doc/<пакет>/copyright`. Машиночитаемый формат:

```
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: hello-cat

Files: *
Copyright: 2026 Вася Пупкин
License: MIT
 Текст лицензии — строками с пробелом в начале.
```

Лицензия pelmeni — в его `LICENSE`.
