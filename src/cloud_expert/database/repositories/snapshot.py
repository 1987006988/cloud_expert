from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.repositories.base import BaseRepository


class SnapshotRecordRepository(BaseRepository[SnapshotRecord]):
    model = SnapshotRecord

    def get_by_source_hash(self, source_id: str, content_hash: str) -> SnapshotRecord | None:
        return next(
            iter(self.list({"source_id": source_id, "content_hash": content_hash}, limit=1)), None
        )

    def list_for_source(self, source_id: str) -> list[SnapshotRecord]:
        return self.list({"source_id": source_id})
