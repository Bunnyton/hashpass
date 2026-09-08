"""Ordered task catalog (task number -> published task), persisted as JSON."""
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CatalogEntry:
    """One numbered task in the curriculum."""

    number: int
    name: str
    version: str
    title: str
    digest: str

    @property
    def ref(self) -> str:
        """The image/task ref `name:version`."""
        return f"{self.name}:{self.version}"

    def as_dict(self) -> dict[str, object]:
        """Serializable view (used by the /catalog response and the web dashboard)."""
        return {"number": self.number, "name": self.name, "version": self.version,
                "title": self.title, "digest": self.digest, "ref": self.ref}


class Catalog:
    """A task-number -> task map persisted as JSON. Free order: the number is display/order only."""

    def __init__(self, path: Path) -> None:
        """Open (creating on write) the catalog at path."""
        self._path = Path(path)

    def _load(self) -> dict[str, dict[str, object]]:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def put(self, entry: CatalogEntry) -> None:
        """Add or overwrite the task at `entry.number`."""
        data = self._load()
        data[str(entry.number)] = {"name": entry.name, "version": entry.version,
                                   "title": entry.title, "digest": entry.digest}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def entries(self) -> list[CatalogEntry]:
        """Return all entries ordered by task number."""
        data = self._load()
        return [CatalogEntry(int(n), str(d["name"]), str(d["version"]),
                             str(d["title"]), str(d["digest"]))
                for n, d in sorted(data.items(), key=lambda kv: int(kv[0]))]

    def get(self, number: int) -> CatalogEntry | None:
        """Return the entry at `number`, or None."""
        d = self._load().get(str(number))
        if d is None:
            return None
        return CatalogEntry(number, str(d["name"]), str(d["version"]),
                            str(d["title"]), str(d["digest"]))

    def find(self, ref: str) -> CatalogEntry | None:
        """Return the entry whose ref matches `name:version`, or None."""
        return next((e for e in self.entries() if e.ref == ref), None)
