from pydantic import BaseModel, Field


class EcsSkuParsedRow(BaseModel):
    provider_sku_code: str
    sku_family: str | None = None
    vcpu: str | None = None
    memory: str | None = None
    max_bandwidth: str | None = None
    max_pps: str | None = None
    local_disk: str | None = None
    virtualization_type: str | None = None
    locator: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
