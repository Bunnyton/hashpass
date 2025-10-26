import shlex
import re
from typing import List

class Cmd:
    def __init__(self, raw: str):
        self.raw = raw.strip()
        self.tokens = shlex.split(self.raw)
        self.is_sudo = self.tokens and self.tokens[0] == "sudo"
        self._parse_cmd()

    def _parse_cmd(self):
        """Разбирает команду на основную часть, короткие и длинные флаги и аргументы."""
        tokens = self.tokens[1:] if self.is_sudo else self.tokens
        if not tokens:
            self.basecmd = ""
            self.short_flags = set()
            self.long_flags = set()
            self.args = []
            return

        self.basecmd = tokens[0]
        self.short_flags = set()
        self.long_flags = set()
        self.args = []

        for token in tokens[1:]:
            if token.startswith("--"):
                # длинный флаг: --help или --name=value
                flag = token[2:]
                self.long_flags.add(flag.split("=")[0])
            elif token.startswith("-") and len(token) > 1:
                # короткие флаги: -rf → {'r', 'f'}
                for ch in token[1:]:
                    self.short_flags.add(ch)
            else:
                self.args.append(token)

    # ---- Проверки ----
    def has_flag(self, flag: str) -> bool:
        """Проверяет наличие флага (-f, --force и т.п.)"""
        if flag.startswith("--"):
            return flag[2:] in self.long_flags
        elif flag.startswith("-"):
            return flag[1:] in self.short_flags
        return False

    def __contains__(self, cmd) -> bool:
        if not isinstance(cmd, Cmd):
            return NotImplemented

        if self.basecmd != cmd.basecmd:
            return False

        for flag in cmd.short_flags:
            if flag not in self.short_flags:
                return False

        for flag in cmd.long_flags:
            if flag not in self.long_flags:
                return False

        for arg in cmd.args:
            if arg not in self.args:
                return False
        return True

    # ---- Сравнение ----
    def __eq__(self, other):
        if not isinstance(other, Cmd):
            return NotImplemented
        return (
                self.basecmd == other.basecmd
                and self.short_flags == other.short_flags
                and self.long_flags == other.long_flags
                and self.args == other.args
        )

    def is_similar(self, other) -> bool:
        """Похожи ли команды (флаги и имя совпадают, без учёта аргументов)."""
        if not isinstance(other, Cmd):
            return False
        return (
                self.basecmd == other.cmd
                and self.short_flags == other.short_flags
                and self.long_flags == other.long_flags
        )

    def prefer(self, other):
        """Выбирает более 'первичную' команду (с большим количеством флагов)."""
        score_self = len(self.short_flags) + len(self.long_flags)
        score_other = len(other.short_flags) + len(other.long_flags)
        if score_self > score_other:
            return self
        if score_other > score_self:
            return other
        return self if len(self.raw) >= len(other.raw) else other

    # ---- Утилиты ----
    def summary(self) -> dict:
        """Возвращает разобранную структуру команды."""
        return {
            "sudo": self.is_sudo,
            "cmd": self.basecmd,
            "short_flags": sorted(self.short_flags),
            "long_flags": sorted(self.long_flags),
            "args": self.args,
        }

    def __repr__(self):
        sudo_part = "sudo " if self.is_sudo else ""
        flags = " ".join(
            ["-" + "".join(sorted(self.short_flags))] +
            [f"--{f}" for f in sorted(self.long_flags)]
        ).strip()
        args = " ".join(self.args)
        parts = [sudo_part + self.basecmd, flags, args]
        return "<Cmd: " + " ".join(p for p in parts if p) + ">"


# ---- Парсер нескольких команд ----
def parse_cmds(raw_input: str) -> List[Cmd]:
    """
    Разделяет строку на несколько команд по `&&`, `;` или `||`
    и возвращает список объектов Cmd.
    """
    # Разбиваем по разделителям команд
    parts = re.split(r'\s*(?:&&|\|\||;)\s*', raw_input.strip())
    return [Cmd(part) for part in parts if part.strip()]
