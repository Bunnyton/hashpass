"""Version + best-effort self-update from GitHub releases of the same repo."""
import contextlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

__version__ = "0.2.1"  # bump this AND pyproject, then tag a GitHub release, to ship an update

_REPO = "Bunnyton/hashpass"
_LATEST_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"
_ENV_NO_UPDATE = "HASHPASS_NO_UPDATE"
_ENV_SPEC = "HASHPASS_UPDATE_SPEC"  # override the pip install target (e.g. a subdir dist)
_CHECK_INTERVAL = 24 * 3600
_STAMP = "update.json"


def is_newer(latest: str, current: str) -> bool:
    """Return whether `latest` is a strictly higher dotted-numeric version than `current`."""
    def parts(value: str) -> list[int]:
        out: list[int] = []
        for chunk in value.lstrip("vV").split("."):
            digits = "".join(c for c in chunk if c.isdigit())
            out.append(int(digits) if digits else 0)
        return out

    a, b = parts(latest), parts(current)
    width = max(len(a), len(b))
    a += [0] * (width - len(a))
    b += [0] * (width - len(b))
    return a > b


def latest_release(url: str = _LATEST_URL, *, timeout: float = 5.0) -> str | None:
    """Return the latest release tag from GitHub, or None on any failure (offline-safe)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310  (fixed https URL)
            tag = json.loads(resp.read().decode("utf-8")).get("tag_name")
    except (urllib.error.URLError, ValueError, OSError, TimeoutError):
        return None
    return str(tag) if tag else None


def _should_check(home: Path, *, now: float) -> bool:
    try:
        last = json.loads((home / _STAMP).read_text(encoding="utf-8")).get("last", 0)
    except (OSError, ValueError):
        last = 0
    return (now - float(last)) >= _CHECK_INTERVAL


def _write_stamp(home: Path, *, now: float) -> None:
    with contextlib.suppress(OSError):
        home.mkdir(parents=True, exist_ok=True)
        (home / _STAMP).write_text(json.dumps({"last": now}), encoding="utf-8")


def _pip_install(tag: str) -> bool:
    spec = os.environ.get(_ENV_SPEC, f"git+https://github.com/{_REPO}@{tag}")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--user", "--quiet",
                        "--break-system-packages", spec], check=True, timeout=600)
    except (subprocess.SubprocessError, OSError):
        return False
    return True


def check_and_update(home: Path, module: str, argv: list[str], *,  # noqa: PLR0913
                     now: float | None = None,
                     fetch: Callable[[], str | None] = latest_release,
                     reexec: bool = True) -> bool:
    """
    On launch: if a newer GitHub release exists, pip-install it and re-exec (best-effort).

    Checked at most once per day (stamped in <home>/update.json). Disabled by `--no-update` or
    HASHPASS_NO_UPDATE. Any failure or offline state is swallowed and the tool continues on the
    current version. Returns True when an update was installed.
    """
    if os.environ.get(_ENV_NO_UPDATE) or "--no-update" in argv:
        return False
    now = time.time() if now is None else now
    if not _should_check(home, now=now):
        return False
    _write_stamp(home, now=now)
    latest = fetch()
    if not latest or not is_newer(latest, __version__) or not _pip_install(latest):
        return False
    sys.stderr.write(f"hashpass: обновлено до {latest}\n")
    if reexec:
        os.execv(sys.executable, [sys.executable, "-m", module, *argv])  # noqa: S606
    return True
