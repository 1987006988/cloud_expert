from pydantic import BaseModel, Field


class ObsStorageClassCandidate(BaseModel):
    official_name: str
    tier_code: str
    excerpt: str = Field(min_length=1)
    locator: str = Field(min_length=1)
