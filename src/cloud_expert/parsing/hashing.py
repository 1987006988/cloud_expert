from cloud_expert.ingestion.storage.hashing import sha256_hex


def field_value_hash(*parts: str | None) -> str:
    payload = "\x1f".join(part or "" for part in parts).encode("utf-8")
    return sha256_hex(payload)
