import hashlib
import hmac

_GKEY_ALGO = hashlib.sha256


def local_key(task_id: str, stage: int, nonce: str) -> str:
    """
    Generate a deterministic progress key from task_id, stage, and nonce.

    Format: key{<hex16>}
    """
    d = hashlib.sha256(f"{task_id}|{stage}|{nonce}".encode("utf-8")).digest()
    return "key{" + d[:8].hex() + "}"


def global_key(server_secret: bytes, student_id: str, task_id: str) -> str:
    """Unforgeable global credit: HMAC(server_secret, student_id || NUL || task_id). §6."""
    if "\x00" in student_id or "\x00" in task_id:
        msg = "student_id/task_id must not contain NUL"
        raise ValueError(msg)
    payload = student_id.encode("utf-8") + b"\x00" + task_id.encode("utf-8")
    return "gkey{" + hmac.new(server_secret, payload, _GKEY_ALGO).hexdigest() + "}"
