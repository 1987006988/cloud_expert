from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.repositories.base import BaseRepository


class SourceDocumentRepository(BaseRepository[SourceDocument]):
    model = SourceDocument

    def get_by_url_hash(self, url: str, content_hash: str) -> SourceDocument | None:
        return next(iter(self.list({"url": url, "content_hash": content_hash}, limit=1)), None)


class EvidenceRepository(BaseRepository[Evidence]):
    model = Evidence
