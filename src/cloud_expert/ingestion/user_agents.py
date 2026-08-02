TEST_USER_AGENT = "CloudCompetitiveExpert-Test/0.1"
PRODUCTION_USER_AGENT = "CloudCompetitiveExpert/0.1 (+project-contact-placeholder)"
BROWSER_COMPATIBLE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)


def resolve_user_agent(profile: str, *, env: str = "development") -> str:
    if profile == "browser_compatible":
        return BROWSER_COMPATIBLE_USER_AGENT
    if profile == "cloud_expert_bot" and env == "production":
        return PRODUCTION_USER_AGENT
    return TEST_USER_AGENT


def resolve_request_headers(profile: str, *, env: str = "development") -> dict[str, str]:
    headers = {"User-Agent": resolve_user_agent(profile, env=env)}
    if profile == "browser_compatible":
        headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
    return headers
