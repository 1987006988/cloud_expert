TEST_USER_AGENT = "CloudCompetitiveExpert-Test/0.1"
PRODUCTION_USER_AGENT = "CloudCompetitiveExpert/0.1 (+project-contact-placeholder)"


def resolve_user_agent(profile: str, *, env: str = "development") -> str:
    if profile == "cloud_expert_bot" and env == "production":
        return PRODUCTION_USER_AGENT
    return TEST_USER_AGENT
