"""Client-side credential cache: reuse a login token per registry until it expires."""
import json
from pathlib import Path


class CredentialCache:
    """Per-registry {token, expiry} cache, persisted as JSON. Dev/test only, never shipped."""

    def __init__(self, path: Path) -> None:
        """Open (creating on write) the credential cache at path."""
        self._path = Path(path)

    def _load(self) -> dict[str, dict[str, object]]:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def save(self, registry: str, token: str, expiry: int) -> None:
        """Persist a token and its expiry (unix seconds) for a registry URL."""
        data = self._load()
        data[registry] = {"token": token, "expiry": expiry}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self._path.chmod(0o600)  # holds a live bearer token: not world-readable

    def cached_token(self, registry: str, *, now: float) -> str | None:
        """Return a still-valid cached token for registry, or None if absent/expired."""
        entry = self._load().get(registry)
        if entry is None:
            return None
        expiry = entry.get("expiry")
        token = entry.get("token")
        if not isinstance(expiry, int) or not isinstance(token, str) or now >= expiry:
            return None
        return token
