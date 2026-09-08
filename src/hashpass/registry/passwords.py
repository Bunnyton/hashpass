"""PBKDF2 password hashing + a JSON-backed user store with profiles and roles."""
import hashlib
import hmac
import json
import secrets
import time
from functools import cache
from pathlib import Path

_PW_SCHEME = "pbkdf2_sha256"
_PW_ALGO = "sha256"
_PW_ITERATIONS = 600_000
_SALT_BYTES = 16
_PW_FIELDS = 4

ROLES = ("student", "author", "admin")


def hash_password(password: str, *, iterations: int = _PW_ITERATIONS,
                  salt: bytes | None = None) -> str:
    """Hash a password as `pbkdf2_sha256$iterations$salt_hex$hash_hex` (random salt if unset)."""
    if salt is None:
        salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(_PW_ALGO, password.encode("utf-8"), salt, iterations)
    return f"{_PW_SCHEME}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check of a password against a stored `pbkdf2_sha256$…` record."""
    parts = encoded.split("$")
    if len(parts) != _PW_FIELDS or parts[0] != _PW_SCHEME:
        return False
    _, iters, salt_hex, hash_hex = parts
    try:
        iterations = int(iters)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(_PW_ALGO, password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


@cache
def _decoy_record() -> str:
    """Return a fixed PBKDF2 record so an unknown-user login still runs one hash (constant-time)."""
    return hash_password("\x00decoy\x00")


def _record(pw_hash: str, role: str, full_name: str, group: str,  # noqa: PLR0913, PLR0917
            comment: str, created_at: float) -> dict[str, object]:
    return {"pw": pw_hash, "role": role, "full_name": full_name,
            "group": group, "comment": comment, "created_at": created_at}


def _normalize(value: object) -> dict[str, object]:
    """Coerce a stored value (legacy bare-string hash, or a record dict) into a full record."""
    if isinstance(value, str):
        return _record(value, "student", "", "", "", 0.0)
    v = value if isinstance(value, dict) else {}
    return _record(str(v.get("pw", "")), str(v.get("role", "student")),
                   str(v.get("full_name", "")), str(v.get("group", "")),
                   str(v.get("comment", "")), float(v.get("created_at", 0.0)))


class UserStore:
    """User -> {pw, role, full_name, group, comment, created_at}, persisted as JSON (chmod 0600)."""

    def __init__(self, path: Path) -> None:
        """Open (creating on write) the user store at path."""
        self._path = Path(path)

    def _load(self) -> dict[str, dict[str, object]]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return {user: _normalize(value) for user, value in raw.items()}

    def _save(self, users: dict[str, dict[str, object]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(users, indent=2), encoding="utf-8")
        self._path.chmod(0o600)  # PBKDF2 hashes + profiles: not world-readable

    def add(self, user: str, password: str, *, role: str = "student",  # noqa: PLR0913
            full_name: str = "", group: str = "", comment: str = "") -> None:
        """Add or replace a user with a freshly salted password hash and a profile."""
        if role not in ROLES:
            msg = f"unknown role: {role!r}"
            raise ValueError(msg)
        users = self._load()
        users[user] = _record(hash_password(password), role, full_name, group, comment, time.time())
        self._save(users)

    def has(self, user: str) -> bool:
        """Return whether a user is registered (regardless of password)."""
        return user in self._load()

    def verify(self, user: str, password: str) -> bool:
        """Return whether password matches the stored hash for user (False if unknown)."""
        rec = self._load().get(user)
        if rec is None:
            verify_password(password, _decoy_record())  # run one PBKDF2 anyway: no timing leak
            return False
        return verify_password(password, str(rec["pw"]))

    def get(self, user: str) -> dict[str, object] | None:
        """Return the user's public profile (no password hash), or None if unknown."""
        rec = self._load().get(user)
        if rec is None:
            return None
        return {"user": user, "role": rec["role"], "full_name": rec["full_name"],
                "group": rec["group"], "comment": rec["comment"], "created_at": rec["created_at"]}

    def role(self, user: str) -> str | None:
        """Return the user's role, or None if unknown."""
        rec = self._load().get(user)
        return None if rec is None else str(rec["role"])

    def set_role(self, user: str, role: str) -> None:
        """Change a user's role (KeyError if unknown, ValueError on a bad role)."""
        if role not in ROLES:
            msg = f"unknown role: {role!r}"
            raise ValueError(msg)
        users = self._load()
        if user not in users:
            raise KeyError(user)
        users[user]["role"] = role
        self._save(users)

    def all_users(self) -> list[dict[str, object]]:
        """Return every user's public profile, sorted by login (for the dashboard)."""
        return [profile for user in sorted(self._load()) if (profile := self.get(user)) is not None]
