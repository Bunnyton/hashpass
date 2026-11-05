---
tags: приз, telnet, сеть, терминал
---
# telnet: терминал на другом конце провода

Призовое задание: «Звёздные войны», нарисованные буквами, по сети. А заодно — знакомство с
`telnet`, одной из самых старых сетевых программ: она открывает соединение с другим
компьютером и превращает твой терминал в «трубку» к нему.

## Что такое telnet

`telnet хост [порт]` устанавливает TCP-соединение и дальше просто передаёт: что набрал ты —
туда, что ответили — на экран. Без порта он стучится в порт 23, «телнетовский»:

    $ grep -E '^telnet' /etc/services
    telnet		23/tcp
    telnets		992/tcp				# Telnet over SSL

В 1970–90-е так заходили на удалённые машины: набрал `telnet сервер`, ввёл логин и пароль —
и работаешь там, будто сидишь рядом.

## Подключение

    $ telnet telehack.com
    Trying 64.13.139.230...
    Connected to telehack.com.
    Escape character is '^]'.

    Connected to TELEHACK port 103

    It is 3:18 pm on Tuesday, November 3, 2026 in Mountain View, California, USA.
    There are 142 local users. There are 26657 hosts on the network.

    May the command line live forever.

    Command, one of the following:
      ?            a2           advent       basic        bf           c8
      ...

**Telehack** — музей-симулятор интернета 1980-х: старые игры (`advent`, `zork`), BASIC,
календарь фаз Луны `phoon`, `cowsay` и много чего ещё. `help` покажет всё с описаниями.

## Как выйти

Самая важная строчка — `Escape character is '^]'`. Пока соединение открыто, все клавиши,
включая `Ctrl+C`, уходят на тот конец. Чтобы вернуться к самому telnet, нажми `Ctrl+]`:
появится приглашение `telnet>`, там `quit` (или `close`). Если сервер сам закрыл соединение,
telnet напишет `Connection closed by foreign host.` и выйдет.

## telnet как отвёртка

Сам по себе telnet ничего не знает о протоколах — поэтому им удобно проверять, открыт ли
порт, и разговаривать с сервером «руками». Например, спросить веб-сервер по HTTP:

    $ telnet info.cern.ch 80
    Trying 188.184.67.127...
    Connected to info.cern.ch.
    Escape character is '^]'.
    HEAD / HTTP/1.0
    Host: info.cern.ch

    HTTP/1.1 200 OK
    Date: Tue, 03 Nov 2026 23:18:52 GMT
    Server: Apache
    ...

(info.cern.ch — адрес самого первого сайта в мире.) А если порт закрыт:

    $ telnet localhost 9
    Trying ::1...
    Trying 127.0.0.1...
    telnet: Unable to connect to remote host: Connection refused

Для той же проверки есть `nc` (netcat):

    $ nc -zv -w3 telehack.com 23
    Connection to telehack.com (64.13.139.230) 23 port [tcp/telnet] succeeded!

## Почему сейчас вместо telnet — ssh

telnet передаёт всё **открытым текстом**, включая логин и пароль: любой, кто видит трафик
(тот же Wi-Fi в кафе), прочитает их. Поэтому удалённо на серверы сегодня заходят по `ssh` —
то же самое, но всё зашифровано. telnet остался для музеев вроде telehack, старого
сетевого железа и проверки портов.

## ASCII-кино

Анимацию «Звёздных войн» буквами вручную собрал Саймон Янсен (Новая Зеландия): большой кусок
фильма, кадр за кадром, текстом. Оригинал до сих пор смотрится в браузере на
[asciimation.co.nz](https://www.asciimation.co.nz/).

## Источники

- [telnet(1) — manpages.debian.org](https://manpages.debian.org/trixie/inetutils-telnet/telnet.1.en.html)
  — команды после `Ctrl+]`.
- [RFC 854](https://www.rfc-editor.org/rfc/rfc854) — спецификация Telnet 1983 года.
- [telehack.com](https://telehack.com/) — тот же Telehack, только в браузере.
- [ASCIIMation](https://www.asciimation.co.nz/) — «Звёздные войны» Саймона Янсена.
