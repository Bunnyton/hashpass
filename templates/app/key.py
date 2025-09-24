import hashlib

def key(*args) -> str:

    phrase = ""
    for arg in args:
        phrase += str(arg)

    # SHA-256 -> 32 байта
    digest = hashlib.sha256(phrase.encode("utf-8")).digest()

    # fold 32 -> 16 (XOR первых 16 байт со вторыми 16)
    folded16 = bytes(digest[i] ^ digest[i + 16] for i in range(16))

    # fold 16 -> 8 (XOR первых 8 байт со вторыми 8)
    folded8 = bytes(folded16[i] ^ folded16[i + 8] for i in range(8))

    # hex-представление = 16 символов
    return "key{" + folded8.hex() + "}"
