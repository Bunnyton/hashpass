#!/bin/sh
# hashpass, x86_64 images on another processor (qemu-user): write what did not start, and how man
# fares, for the host to show. Never fails: a missing journal or a crashing man is the news.
sleep 20
{
    echo "## failed units"
    systemctl --failed --no-legend --plain 2>&1
    echo "## man"
    man -P cat man >/dev/null 2>/tmp/hp-man.err; echo "без выключателя: exit=$?"; tail -3 /tmp/hp-man.err
    MAN_DISABLE_SECCOMP=1 /usr/bin/man -P cat man >/dev/null 2>/tmp/hp-man.err
    echo "MAN_DISABLE_SECCOMP=1: exit=$?"; tail -3 /tmp/hp-man.err
    echo "## system"
    uname -a
    echo "page size: $(getconf PAGESIZE)"
    echo "## errors"
    journalctl -b -p err --no-pager -n 200 2>&1 || echo "журнал недоступен"
} > /var/log/hp-emulated-report.txt 2>&1
exit 0
