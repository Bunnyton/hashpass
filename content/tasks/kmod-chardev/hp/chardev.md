# Символьное устройство

В Linux устройство — это файл в `/dev`. Когда программа читает такой файл, данные ей отдаёт не
диск, а драйвер: ядро зовёт его функцию `read`. Символьное (character) устройство отдаёт байты
потоком — как терминал или `/dev/urandom`.

Какие функции у твоего файла, драйвер сообщает таблицей `struct file_operations`:

```c
static ssize_t moon_read(struct file *f, char __user *buf, size_t n, loff_t *off);

static const struct file_operations moon_fops = {
        .owner = THIS_MODULE,
        .read  = moon_read,
};
```

`read` получает буфер программы `buf` (до `n` байт) и `*off` — сколько из файла уже прочитано.
Вернуть нужно, сколько байт отдал, а `0` — «файл кончился»: `cat` читает, пока не получит 0.
Писать в `buf` напрямую нельзя — это память программы, а не ядра. Копирует `copy_to_user`, а
`simple_read_from_buffer(buf, n, off, данные, длина)` делает всё сразу: копирует нужный кусок,
сдвигает `*off` и вернёт 0, когда данные кончились.

Проще всего завести свой файл в `/dev` — как misc-устройство: ядро само выдаст номер и создаст
`/dev/<имя>`. Подключается `<linux/miscdevice.h>`:

```c
static struct miscdevice moon_dev = {
        .minor = MISC_DYNAMIC_MINOR,
        .name  = "moon",              /* появится /dev/moon */
        .fops  = &moon_fops,
};

module_misc_device(moon_dev);         /* сам регистрирует и убирает — init и exit не нужны */
```
