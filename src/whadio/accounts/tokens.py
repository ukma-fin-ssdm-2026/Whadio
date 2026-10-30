import hashlib


def supplied_token_hash(token: str) -> str | None:
    try:
        encoded = token.encode()
    except UnicodeEncodeError:
        return None
    return hashlib.sha256(encoded).hexdigest()
