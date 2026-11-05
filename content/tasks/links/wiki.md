---
tags: файлы, ссылки, ln, symlink
---
# Ссылки: символьные и жёсткие

Бывает, один файл нужен в нескольких местах: программа ищет конфиг у себя, а правишь ты его в
домашнем каталоге. Копия не годится — правки разъедутся. Нужна **ссылка**. В Linux их два
вида, и устроены они совсем по-разному.

## Символьная ссылка — ярлык с путём

Символьная (soft, symlink) ссылка — крошечный файл, внутри которого записан **путь**. Открываешь
ссылку — система идёт по этому пути. Создаёт её `ln -s`; порядок как у `cp`: сначала на что,
потом имя ссылки:

    $ ln -s music/rock/best.txt fav.txt
    $ ln -s music/rock rock
    $ ls -l
    total 0
    lrwxrwxrwx 1 anya anya 19 Nov  4 02:18 fav.txt -> music/rock/best.txt
    drwxrwxr-x 3 anya anya 60 Nov  4 02:18 music
    lrwxrwxrwx 1 anya anya 10 Nov  4 02:18 rock -> music/rock

Буква `l` в начале строки и стрелка — это ссылка. Размер — длина записанного пути (19 символов
в `music/rock/best.txt`), а не размер файла. Работают ссылки как настоящие:

    $ cat fav.txt
    Highway to Hell
    $ ls rock
    best.txt

Что записано внутри, покажет `readlink`:

    $ readlink fav.txt
    music/rock/best.txt

Имя занято — `ln` откажется; заменить существующую ссылку помогает ключ `-f` (force):

    $ ln -s music/rock/best.txt fav.txt
    ln: failed to create symbolic link 'fav.txt': File exists

## Относительный путь считается от ссылки

Самая частая ловушка. Относительный путь внутри ссылки отсчитывается не от того места, где
ты стоял, создавая её, а от каталога, **где лежит сама ссылка**. Перенесли ссылку — путь
теперь ведёт в другое место:

    $ mkdir shelf; mv fav.txt shelf/
    $ ls -l shelf
    total 0
    lrwxrwxrwx 1 anya anya 19 Nov  4 02:18 fav.txt -> music/rock/best.txt
    $ cat shelf/fav.txt
    cat: shelf/fav.txt: No such file or directory

Ссылка ищет `shelf/music/rock/best.txt` — а его нет. Это **битая** ссылка; многие терминалы
красят такие красным. Путь от корня работает откуда угодно:

    $ ln -sf /tmp/tmp.lm9zsKejxO/lnd/music/rock/best.txt shelf/fav.txt
    $ cat shelf/fav.txt
    Highway to Hell

Относительные ссылки тоже нужны: они переживают перенос, если переезжают **вместе** с целью
(весь проект в другой каталог).

## Ссылка хранит путь, а не файл

Символьной ссылке всё равно, что лежит по пути, — и есть ли там что-нибудь вообще. Ссылку можно
сделать на ещё не существующий файл; он появится — ссылка оживёт сама:

    $ ln -s data/today.csv report.csv
    $ cat report.csv
    cat: report.csv: No such file or directory
    $ mkdir data; echo 'id,sum' > data/today.csv
    $ cat report.csv
    id,sum

Так устроены «текущие» версии: `current -> release-42`, `python3 -> python3.13`. Переключить
версию — значит поменять ссылку или то, что лежит по её пути.

## Жёсткая ссылка — ещё одно имя

У файла есть **данные** (их номер — inode) и **имя** в каталоге, указывающее на них. Жёсткая
ссылка — второе имя тех же данных. Делает её `ln` без `-s`:

    $ ln todo.txt todo2.txt
    $ ls -li todo.txt todo2.txt
    341577 -rw-rw-r-- 2 anya anya 22 Nov  4 02:18 todo.txt
    341577 -rw-rw-r-- 2 anya anya 22 Nov  4 02:18 todo2.txt

Номер inode (первый столбец `-i`) одинаковый, а число имён — второй столбец — стало 2. Имена
равноправны: правка через одно видна через другое, а `rm` удаляет **имя**, не данные. Данные
живут, пока есть хоть одно:

    $ rm todo.txt
    $ cat todo2.txt
    купить хлеб
    и молоко

Ограничения: жёсткие ссылки бывают только на файлы и только в пределах одной файловой
системы:

    $ ln music hard_dir
    ln: music: hard link not allowed for directory

## Какую выбрать

| | Символьная (`ln -s`) | Жёсткая (`ln`) |
|---|---|---|
| хранит | путь | те же данные |
| на каталог | можно | нельзя |
| на другой диск | можно | нельзя |
| удалили оригинал | ссылка битая | данные целы |
| видно в `ls -l` | `l` и стрелка | только число имён |

## Источники

- [`man 1 ln`](https://man7.org/linux/man-pages/man1/ln.1.html) — ключи `-s`, `-f`, `-r`.
- [`man 7 symlink`](https://man7.org/linux/man-pages/man7/symlink.7.html) — как система
  обрабатывает символьные ссылки.
- [Символические и жёсткие ссылки Linux — Losst](https://losst.pro/simvolicheskie-i-zhestkie-ssylki-linux)
