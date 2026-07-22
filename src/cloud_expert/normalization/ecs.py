import re


def infer_ecs_family_code(provider_sku_code: str) -> str:
    if provider_sku_code.startswith("ecs."):
        tokens = provider_sku_code.split(".")
        if len(tokens) >= 2:
            return tokens[1]
    token = provider_sku_code.strip().split(".", 1)[0]
    return token or provider_sku_code


def infer_ecs_architecture_from_text(text: str) -> str | None:
    lowered = text.lower()
    if "鲲鹏" in text or "kunpeng" in lowered or provider_prefix_is_kunpeng(text):
        return "arm64"
    if "x86" in lowered:
        return "x86"
    return None


def provider_prefix_is_kunpeng(text: str) -> bool:
    return bool(re.search(r"\bk[a-z]\d", text.lower()))
