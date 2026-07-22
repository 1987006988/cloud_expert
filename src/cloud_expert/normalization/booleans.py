TRUE_TOKENS = {
    "true",
    "yes",
    "y",
    "supported",
    "support",
    "available",
    "enabled",
    "1",
    "支持",
    "是",
    "有",
    "可用",
    "已启用",
}
FALSE_TOKENS = {
    "false",
    "no",
    "n",
    "unsupported",
    "not supported",
    "unavailable",
    "disabled",
    "0",
    "不支持",
    "否",
    "无",
    "不可用",
    "未启用",
}


def normalize_boolean(raw_value: str) -> bool | None:
    text = raw_value.strip().lower()
    if text in TRUE_TOKENS:
        return True
    if text in FALSE_TOKENS:
        return False
    return None
