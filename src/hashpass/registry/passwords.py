"""PBKDF2 password hashing + a JSON-backed user store with profiles and roles."""
import hashlib
import hmac
import json
import re
import secrets
import time
from collections.abc import Iterable
from functools import cache
from pathlib import Path

from hashpass.registry.perms import DEFAULT, clean

_PW_SCHEME = "pbkdf2_sha256"
_PW_ALGO = "sha256"
_PW_ITERATIONS = 600_000
_SALT_BYTES = 16
_PW_FIELDS = 4

ROLES = ("user", "admin")   # spec 2026-10-25 §2: `student` and `author` are gone -- read as `user`
_LEGACY = {"student": "user", "author": "user"}

MIN_PASSWORD_LEN = 8
# safe as a login AND as a per-user progress filename
LOGIN_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
LOGIN_RULE = ("логин — латиницей, одним словом: буквы, цифры и . _ - (до 64 символов), "
              "например nikitin.vn")


class WeakPasswordError(ValueError):
    """A chosen password does not meet the pool's password policy."""


class BadLoginError(ValueError):
    """A login the pool cannot store (non-Latin letters, spaces, @, too long)."""


def validate_login(user: str) -> None:
    """Raise BadLoginError (in Russian, naming what is wrong) unless `user` matches LOGIN_RE."""
    if LOGIN_RE.match(user):
        return
    if any(c.isspace() for c in user):
        why = "в логине не должно быть пробелов"
    elif any(c.isalpha() and not c.isascii() for c in user):
        why = "логин пишется латиницей (английскими буквами)"
    elif len(user) > 64:  # noqa: PLR2004
        why = "логин длиннее 64 символов"
    else:
        why = "в логине недопустимые символы"
    msg = f"{why}; {LOGIN_RULE}"
    raise BadLoginError(msg)


def validate_password(password: str) -> None:
    """
    Enforce the password policy; raise WeakPasswordError (in Russian) if it fails.

    Policy: at least MIN_PASSWORD_LEN characters, with at least one letter, one
    digit, and one special character (anything non-alphanumeric). Kept
    deliberately light -- this is a teaching pool, not a bank.
    """
    if len(password) < MIN_PASSWORD_LEN:
        msg = f"пароль должен быть не короче {MIN_PASSWORD_LEN} символов"
        raise WeakPasswordError(msg)
    if not any(c.isalpha() for c in password):
        msg = "пароль должен содержать хотя бы одну букву"
        raise WeakPasswordError(msg)
    if not any(c.isdigit() for c in password):
        msg = "пароль должен содержать хотя бы одну цифру"
        raise WeakPasswordError(msg)
    if not any(not c.isalnum() for c in password):
        msg = "пароль должен содержать хотя бы один спецсимвол"
        raise WeakPasswordError(msg)


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


def _record(pw_hash: str, role: str, group: str, comment: str,  # noqa: PLR0913
            created_at: float, *, auto_approve: bool = False, tz: str = "",
            perms: list[str] | None = None) -> dict[str, object]:
    rec: dict[str, object] = {"pw": pw_hash, "role": _LEGACY.get(role, role), "group": group,
                              "comment": comment, "created_at": created_at,
                              "auto_approve": auto_approve, "tz": tz}
    if rec["role"] == "admin" and perms is not None:      # no `perms`: an admin from before -- all
        rec["perms"] = sorted(clean(perms, default=DEFAULT))
    return rec


def _normalize(value: object) -> dict[str, object]:
    """Coerce a stored value (legacy bare-string hash, or a record dict) into a current record."""
    if isinstance(value, str):
        return _record(value, "user", "", "", 0.0)
    v = value if isinstance(value, dict) else {}   # older records may carry a dropped full_name
    stored = v.get("perms")
    return _record(str(v.get("pw", "")), str(v.get("role", "user")),
                   str(v.get("group", "")), str(v.get("comment", "")),
                   float(v.get("created_at", 0.0)), auto_approve=bool(v.get("auto_approve", False)),
                   tz=str(v.get("tz", "")), perms=list(stored) if isinstance(stored, list) else None)


class UserStore:
    """
    User -> {pw, role, group, comment, created_at}, persisted as JSON (chmod 0600).

    `group` is structured (for the dashboard filter); `comment` is free-form (the pool's policy).
    """

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

    def add(self, user: str, password: str, *, role: str = "user",
            group: str = "", comment: str = "") -> None:
        """Add or replace a user with a freshly salted password hash, a group, and a comment."""
        role = _LEGACY.get(role, role)
        if role not in ROLES:
            msg = f"unknown role: {role!r}"
            raise ValueError(msg)
        if self.reserved(user):
            msg = f"логин {user} занят"
            raise ValueError(msg)
        users = self._load()
        users[user] = _record(hash_password(password), role, group, comment, time.time(),
                              perms=sorted(DEFAULT) if role == "admin" else None)
        self._save(users)

    def _reserved_path(self) -> Path:
        return self._path.with_name(self._path.stem + "-reserved.json")

    def reserved(self, user: str) -> bool:
        """Whether `user` is the login of a deleted account: it owned a namespace, never reused."""
        try:
            return user in json.loads(self._reserved_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False

    def search(self, query: str) -> list[dict[str, object]]:
        """Profiles whose login or comment contains `query` (case-insensitive), sorted by login."""
        q = query.casefold()
        return [p for p in self.all_users()
                if q in str(p["user"]).casefold() or q in str(p["comment"]).casefold()
                or q in str(p["group"]).casefold()]

    def has(self, user: str) -> bool:
        """Return whether a user is registered (regardless of password)."""
        return user in self._load()

    def set_password(self, user: str, password: str) -> None:
        """Replace a user's password hash, preserving role/group/comment (KeyError if unknown)."""
        users = self._load()
        if user not in users:
            raise KeyError(user)
        users[user]["pw"] = hash_password(password)
        self._save(users)

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
        return {"user": user, "role": rec["role"], "group": rec["group"],
                "comment": rec["comment"], "created_at": rec["created_at"],
                "auto_approve": rec["auto_approve"], "tz": rec["tz"], "perms": rec.get("perms")}

    def stored_roles(self) -> dict[str, str]:
        """Return each login's role as written on disk -- `author` and `student` of old included."""
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return {u: (str(v.get("role", "user")) if isinstance(v, dict) else "user") for u, v in raw.items()}

    def role(self, user: str) -> str | None:
        """Return the user's role, or None if unknown."""
        rec = self._load().get(user)
        return None if rec is None else str(rec["role"])

    def delete(self, user: str) -> bool:
        """Remove a user; return whether one was removed."""
        users = self._load()
        if user not in users:
            return False
        del users[user]
        self._save(users)
        try:
            reserved = json.loads(self._reserved_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            reserved = []
        if user not in reserved:                      # its namespace must never pass to a newcomer
            self._reserved_path().write_text(json.dumps([*reserved, user]), encoding="utf-8")
        return True

    def set_role(self, user: str, role: str) -> None:
        """Change a user's role (KeyError if unknown, ValueError on a bad role)."""
        role = _LEGACY.get(role, role)
        if role not in ROLES:
            msg = f"unknown role: {role!r}"
            raise ValueError(msg)
        users = self._load()
        if user not in users:
            raise KeyError(user)
        if role == "admin" and users[user]["role"] != "admin":
            users[user]["perms"] = sorted(DEFAULT)          # a new admin: everything but `admins`
        elif role != "admin":
            users[user].pop("perms", None)
        users[user]["role"] = role
        self._save(users)

    def set_perms(self, user: str, boxes: Iterable[str]) -> None:
        """Set an admin's permission boxes (KeyError if unknown, ValueError if not an admin)."""
        users = self._load()
        if user not in users:
            raise KeyError(user)
        if users[user]["role"] != "admin":
            msg = f"{user} не админ"
            raise ValueError(msg)
        users[user]["perms"] = sorted(clean(list(boxes), default=DEFAULT))
        self._save(users)

    def set_group(self, user: str, group: str) -> None:
        """Change a user's group (server-side metadata, KeyError if unknown)."""
        users = self._load()
        if user not in users:
            raise KeyError(user)
        users[user]["group"] = group
        self._save(users)

    def set_comment(self, user: str, comment: str) -> None:
        """Change a user's comment (server-side metadata, KeyError if unknown)."""
        users = self._load()
        if user not in users:
            raise KeyError(user)
        users[user]["comment"] = comment
        self._save(users)

    def set_tz(self, user: str, tz: str) -> None:
        """Set the time zone the web shows times in for this user; "" = the browser's (KeyError if unknown)."""
        users = self._load()
        if user not in users:
            raise KeyError(user)
        users[user]["tz"] = tz
        self._save(users)

    def auto_approve(self, user: str) -> bool:
        """Whether this author's tasks approve themselves on push (off by default, admin too)."""
        rec = self._load().get(user)
        return bool(rec and rec["auto_approve"])

    def set_auto_approve(self, user: str, *, on: bool) -> None:
        """Turn an author's auto-approval on/off (KeyError if unknown)."""
        users = self._load()
        if user not in users:
            raise KeyError(user)
        users[user]["auto_approve"] = on
        self._save(users)

    def all_users(self) -> list[dict[str, object]]:
        """Return every user's public profile, sorted by login (for the dashboard)."""
        return [profile for user in sorted(self._load()) if (profile := self.get(user)) is not None]
