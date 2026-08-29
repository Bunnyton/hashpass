from pathlib import Path


def stub_check(rootfs: Path, spec: dict) -> bool:
    """
    Check if a given spec is satisfied in the rootfs.

    Supports:
    - {"kind":"path_exists","path":"..."}
    """
    if spec.get("kind") == "path_exists":
        return (Path(rootfs) / spec["path"]).exists()
    msg = f"unknown check kind: {spec.get('kind')}"
    raise ValueError(msg)
