"""Signed bearer tokens: HMAC(secret, user‖NUL‖expiry) with a 7-day TTL; injectable clock."""
import base64
import hashlib
import hmac

_TOKEN_ALGO = hashlib.sha256
_TOKEN_TTL = 7 * 24 * 60 * 60
_TOKEN_FIELDS = 3
_NUL = "\x00"


def _sign(secret: bytes, user: str, expiry: int) -> str:
    payload = f"{user}{_NUL}{expiry}".encode("utf-8")
    return hmac.new(secret, payload, _TOKEN_ALGO).hexdigest()


def _decode(token: str) -> tuple[str, int, str] | None:
    """Decode `user‖NUL‖expiry‖NUL‖sig`, WITHOUT verifying the signature."""
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    parts = raw.split(_NUL)
    if len(parts) != _TOKEN_FIELDS:
        return None
    user, expiry_s, sig = parts
    try:
        return user, int(expiry_s), sig
    except ValueError:
        return None


def issue_token(secret: bytes, user: str, *, now: float, ttl: int = _TOKEN_TTL) -> str:
    """
    Issue a signed, header-safe bearer token for user; it expires at now + ttl.

    The token is base64url(`user‖NUL‖expiry‖NUL‖sig`) where sig = HMAC(secret,
    user‖NUL‖expiry). base64url keeps it safe inside an HTTP `Authorization` header.

    Raises:
        ValueError: if user contains a NUL byte (which would break framing).

    """
    if _NUL in user:
        msg = "user must not contain NUL"
        raise ValueError(msg)
    expiry = int(now) + ttl
    sig = _sign(secret, user, expiry)
    raw = f"{user}{_NUL}{expiry}{_NUL}{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def verify_token(secret: bytes, token: str, *, now: float) -> str | None:
    """Return the token's user if its signature is valid and it has not expired, else None."""
    decoded = _decode(token)
    if decoded is None:
        return None
    user, expiry, sig = decoded
    if not hmac.compare_digest(sig, _sign(secret, user, expiry)):
        return None
    if now >= expiry:
        return None
    return user


def token_expiry(token: str) -> int | None:
    """Read the expiry (unix seconds) embedded in a token, WITHOUT verifying its signature."""
    decoded = _decode(token)
    return None if decoded is None else decoded[1]


def token_user(token: str) -> str | None:
    """Read the user embedded in a token, WITHOUT verifying its signature."""
    decoded = _decode(token)
    return None if decoded is None else decoded[0]
