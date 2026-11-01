import hashlib


def generated_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def supplied_token_hash(token: str) -> str | None:
    try:
        encoded = token.encode()
    except UnicodeEncodeError:
        return None
    return hashlib.sha256(encoded).hexdigest()
