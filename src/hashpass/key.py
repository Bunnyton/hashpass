import hashlib


def local_key(task_id: str, stage: int, nonce: str) -> str:
    """
    Generate a deterministic progress key from task_id, stage, and nonce.

    Format: key{<hex16>}
    """
    d = hashlib.sha256(f"{task_id}|{stage}|{nonce}".encode()).digest()
    return "key{" + d[:8].hex() + "}"
