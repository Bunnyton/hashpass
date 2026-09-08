"""Pool server configuration (registration toggle), persisted as JSON."""
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ServerConfig:
    """Runtime-adjustable pool settings; the admin toggles these from the web UI."""

    registration_open: bool = True


def load_config(path: Path) -> ServerConfig:
    """Load the config from `path`, or return defaults if it does not exist."""
    p = Path(path)
    if not p.exists():
        return ServerConfig()
    data = json.loads(p.read_text(encoding="utf-8"))
    return ServerConfig(registration_open=bool(data.get("registration_open", True)))


def save_config(path: Path, config: ServerConfig) -> None:
    """Persist the config to `path` (creating parent dirs)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"registration_open": config.registration_open}, indent=2),
                 encoding="utf-8")
