from cloud_expert.database.models.ingestion import IngestionRun
from cloud_expert.database.repositories.base import BaseRepository


class IngestionRunRepository(BaseRepository[IngestionRun]):
    model = IngestionRun

    def list_for_source(self, source_id: str) -> list[IngestionRun]:
        return self.list({"source_id": source_id})
