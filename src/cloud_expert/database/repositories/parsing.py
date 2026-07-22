from cloud_expert.database.models.parsing import ParsedFieldCandidate, ParsingRun
from cloud_expert.database.repositories.base import BaseRepository


class ParsingRunRepository(BaseRepository[ParsingRun]):
    model = ParsingRun


class ParsedFieldCandidateRepository(BaseRepository[ParsedFieldCandidate]):
    model = ParsedFieldCandidate
