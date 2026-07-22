TRUE_TOKENS = {"true", "yes", "supported", "支持", "是", "有"}
FALSE_TOKENS = {"false", "no", "unsupported", "不支持", "否", "无"}


def normalize_boolean(raw_value: str) -> bool | None:
    text = raw_value.strip().lower()
    if text in TRUE_TOKENS:
        return True
    if text in FALSE_TOKENS:
        return False
    return None
