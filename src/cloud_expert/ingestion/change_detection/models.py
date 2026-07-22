from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FieldChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    old_value: Any
    new_value: Any


class ChangeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    previous_snapshot_id: str | None
    current_snapshot_id: str
    change_status: str
    changes: list[FieldChange] = Field(default_factory=list)
