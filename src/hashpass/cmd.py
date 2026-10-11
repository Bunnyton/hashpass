"""Normalized shell command parsing/comparison."""
import re
import shlex


class Cmd:
    """Normalized shell command with parsing and comparison methods."""

    def __init__(self, raw: str) -> None:
        """Parse a shell command string into components."""
        self.raw = raw.strip()
        self.tokens = shlex.split(self.raw)
        self.is_sudo = bool(self.tokens) and self.tokens[0] == "sudo"
        self._parse()

    def _parse(self) -> None:
        tokens = self.tokens[1:] if self.is_sudo else self.tokens
        self.short_flags: set[str] = set()
        self.long_flags: set[str] = set()
        self.args: list[str] = []
        self.basecmd = tokens[0] if tokens else ""
        for token in tokens[1:]:
            if token.startswith("--"):
                self.long_flags.add(token[2:].split("=")[0])
            elif token.startswith("-") and len(token) > 1:
                self.short_flags.update(token[1:])
            else:
                self.args.append(token)

    def has_flag(self, flag: str) -> bool:
        """
        Whether the command carries `flag`.

        `--long` matches a long option; `-x` a short letter anywhere in a bundle (`-la` has `-l`);
        a longer single-dash word is first looked up whole (find-style `-mindepth`, `-type`) and
        otherwise read as a bundle of letters (`-rf` == `-fr`).
        """
        if flag.startswith("--"):
            return flag[2:] in self.long_flags
        if flag.startswith("-") and len(flag) > 1:
            if len(flag) > 2 and flag in self.tokens:  # noqa: PLR2004  (more than one letter)
                return True
            return all(ch in self.short_flags for ch in flag[1:])
        return False

    def __eq__(self, other: object) -> bool:
        """Check if two Cmd objects are exactly equal."""
        if not isinstance(other, Cmd):
            return NotImplemented
        return (self.basecmd == other.basecmd and self.short_flags == other.short_flags
                and self.long_flags == other.long_flags and self.args == other.args)

    def __hash__(self) -> int:
        """Return hash of the command components."""
        return hash((self.basecmd, frozenset(self.short_flags),
                     frozenset(self.long_flags), tuple(self.args)))

    def __contains__(self, cmd: object) -> bool:
        """Check if this command contains another as a subset."""
        if not isinstance(cmd, Cmd):
            return False
        return (self.basecmd == cmd.basecmd
                and cmd.short_flags <= self.short_flags
                and cmd.long_flags <= self.long_flags
                and all(a in self.args for a in cmd.args))

    def is_similar(self, other: object) -> bool:
        if not isinstance(other, Cmd):
            return False
        return (self.basecmd == other.basecmd
                and self.short_flags == other.short_flags
                and self.long_flags == other.long_flags)

    def __repr__(self) -> str:
        """Return string representation of the command."""
        sudo = "sudo " if self.is_sudo else ""
        return f"<Cmd {sudo}{self.basecmd} {sorted(self.short_flags)} {self.args}>"


def parse_cmds(raw: str) -> list[Cmd]:
    parts = re.split(r"\s*(?:&&|\|\||;)\s*", raw.strip())
    return [Cmd(p) for p in parts if p.strip()]
