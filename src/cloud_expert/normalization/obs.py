STORAGE_CLASS_CODES = {
    "标准存储": "standard",
    "低频访问存储": "infrequent_access",
    "归档存储": "archive",
    "深度归档存储": "deep_archive",
}


def normalize_storage_class_code(raw_name: str) -> str:
    compact = raw_name.strip()
    return STORAGE_CLASS_CODES.get(compact, compact.lower().replace(" ", "_"))
