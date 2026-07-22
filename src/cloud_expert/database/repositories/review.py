from cloud_expert.database.models.review import DataQualityIssue, ReviewItem
from cloud_expert.database.repositories.base import BaseRepository


class ReviewItemRepository(BaseRepository[ReviewItem]):
    model = ReviewItem


class DataQualityIssueRepository(BaseRepository[DataQualityIssue]):
    model = DataQualityIssue
