"""PBKDF2 password hashing + a JSON-backed user store (dev/test only, never plaintext)."""
import hashlib
import hmac
import json
import secrets
from pathlib import Path

_PW_SCHEME = "pbkdf2_sha256"
_PW_ALGO = "sha256"
_PW_ITERATIONS = 600_000
_SALT_BYTES = 16
_PW_FIELDS = 4


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


class UserStore:
    """User -> PBKDF2 password record, persisted as JSON. Dev/test only, never shipped."""

    def __init__(self, path: Path) -> None:
        """Open (creating on write) the user store at path."""
        self._path = Path(path)

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def add(self, user: str, password: str) -> None:
        """Add or replace a user with a freshly salted password hash."""
        users = self._load()
        users[user] = hash_password(password)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(users, indent=2), encoding="utf-8")

    def verify(self, user: str, password: str) -> bool:
        """Return whether password matches the stored hash for user (False if unknown)."""
        encoded = self._load().get(user)
        if encoded is None:
            return False
        return verify_password(password, encoded)
