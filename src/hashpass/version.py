"""Version + self-update on launch: track the `main` branch of the GitHub repo by commit."""
import json
import os
import subprocess
import sys
from collections.abc import Callable
from importlib import metadata

__version__ = "0.3.4"  # informational; updates follow the commit on `main`, not this number

_REPO = "Bunnyton/hashpass"
_REPO_URL = f"https://github.com/{_REPO}"
_BRANCH = "main"
_ENV_NO_UPDATE = "HASHPASS_NO_UPDATE"
_ENV_UPDATED = "HASHPASS_JUST_UPDATED"   # set across the re-exec so one launch updates at most once
_LS_REMOTE_TIMEOUT = 4.0


def installed_commit() -> str | None:
    """
    Return the commit this copy was pip-installed from (`git+…@main`), else None.

    pip records it in the dist-info's `direct_url.json`. An editable/local install (a developer
    checkout) has no vcs commit -> None, so it is never replaced behind the developer's back.
    """
    try:
        info = json.loads(metadata.distribution("hashpass").read_text("direct_url.json") or "")
    except (metadata.PackageNotFoundError, ValueError, OSError):
        return None
    vcs = info.get("vcs_info") or {}
    if _REPO.lower() not in str(info.get("url", "")).lower():
        return None
    return str(vcs.get("commit_id") or "") or None


def remote_commit(timeout: float = _LS_REMOTE_TIMEOUT) -> str | None:
    """Return the current commit of `main` on GitHub (`git ls-remote`), or None offline."""
    try:
        out = subprocess.run(["git", "ls-remote", _REPO_URL, f"refs/heads/{_BRANCH}"],
                             capture_output=True, text=True, timeout=timeout, check=True,
                             env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    sha = out.split()[0] if out.split() else ""
    return sha if len(sha) == 40 else None   # noqa: PLR2004  (a full git sha)


def _pip_install(commit: str) -> bool:
    pip = [sys.executable, "-m", "pip", "install", "--user", "--quiet", "--upgrade",
           "--force-reinstall", "--no-deps"]
    try:
        helptext = subprocess.run([*pip[:4], "--help"], capture_output=True, text=True,
                                  timeout=60, check=False).stdout
        if "--break-system-packages" in helptext:     # PEP 668 distros; old pip lacks the flag
            pip.append("--break-system-packages")
        subprocess.run([*pip, f"git+{_REPO_URL}@{commit}"], check=True, timeout=600)
    except (subprocess.SubprocessError, OSError):
        return False
    return True


def check_and_update(module: str, argv: list[str], *,  # noqa: PLR0913
                     fetch: Callable[[], str | None] = remote_commit,
                     installed: Callable[[], str | None] = installed_commit,
                     write: Callable[[str], object] = sys.stderr.write,
                     reexec: bool = True) -> bool:
    """
    On every launch: if `main` moved past the installed commit, pip-install it and re-exec.

    Best-effort: offline, a non-git install, or a failed pip leaves the current copy running.
    Disabled by `--no-update` or HASHPASS_NO_UPDATE. Returns True when an update was installed.
    """
    if os.environ.get(_ENV_NO_UPDATE) or os.environ.get(_ENV_UPDATED) or "--no-update" in argv:
        return False
    current = installed()
    if current is None:
        return False
    latest = fetch()
    if not latest or latest == current:
        return False
    write(f"\x1b[36mобновляю {module} ({current[:7]} → {latest[:7]})…\x1b[0m\n")
    if not _pip_install(latest):
        write("\x1b[33mобновить не удалось — работаю на текущей версии\x1b[0m\n")
        return False
    write(f"\x1b[32m{module} обновлён\x1b[0m\n")
    if reexec:
        os.environ[_ENV_UPDATED] = "1"
        argv = [a for a in argv if a != "--no-update"]
        os.execv(sys.executable, [sys.executable, "-m", module, *argv])  # noqa: S606
    return True
