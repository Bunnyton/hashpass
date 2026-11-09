# pacman

Собрать пакет — полдела. В Arch его ставит **pacman** — тот же apt, только с ключами-буквами:

| apt / dpkg | pacman |
|---|---|
| `apt install ./файл.deb` | `pacman -U файл.pkg.tar.zst` |
| `apt install имя` | `pacman -S имя` |
| `apt remove имя` | `pacman -R имя` |
| `dpkg -l имя` | `pacman -Q имя` |
| `apt show имя` | `pacman -Qi имя` |
| `dpkg -L имя` | `pacman -Ql имя` |

Ставить, как и всегда, может только root. pacman здесь настоящий, но живёт рядом с apt: его база
`/var/lib/pacman` пустая, и о пакетах Debian он ничего не знает.
