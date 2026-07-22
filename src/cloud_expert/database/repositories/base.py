from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cloud_expert.common.exceptions import InvalidOperationError, NotFoundError
from cloud_expert.database.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository[ModelT: Base]:
    """Small SQLAlchemy repository with basic CRUD and equality filters."""

    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, data: Mapping[str, Any]) -> ModelT:
        entity = self.model(**dict(data))
        self.session.add(entity)
        self.session.flush()
        self.session.refresh(entity)
        return entity

    def get_by_id(self, entity_id: int) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def require_by_id(self, entity_id: int) -> ModelT:
        entity = self.get_by_id(entity_id)
        if entity is None:
            raise NotFoundError(f"{self.model.__name__} id={entity_id} was not found")
        return entity

    def list(
        self, filters: Mapping[str, Any] | None = None, *, limit: int = 100, offset: int = 0
    ) -> list[ModelT]:
        statement = self._apply_filters(select(self.model), filters or {})
        statement = statement.limit(limit).offset(offset)
        return list(self.session.scalars(statement).all())

    def update(self, entity_id: int, data: Mapping[str, Any]) -> ModelT | None:
        entity = self.get_by_id(entity_id)
        if entity is None:
            return None
        for key, value in data.items():
            if value is not None:
                setattr(entity, key, value)
        self.session.flush()
        self.session.refresh(entity)
        return entity

    def deactivate(self, entity_id: int) -> ModelT:
        entity = self.require_by_id(entity_id)
        if hasattr(entity, "is_active"):
            entity.is_active = False
        elif hasattr(entity, "product_status"):
            entity.product_status = "retired"
        elif hasattr(entity, "review_status"):
            entity.review_status = "rejected"
        else:
            raise InvalidOperationError(f"{self.model.__name__} has no supported inactive state")
        self.session.flush()
        self.session.refresh(entity)
        return entity

    @contextmanager
    def transaction(self) -> Iterator["BaseRepository[ModelT]"]:
        with self.session.begin():
            yield self

    def _apply_filters(
        self, statement: Select[tuple[ModelT]], filters: Mapping[str, Any]
    ) -> Select[tuple[ModelT]]:
        for field, value in filters.items():
            if value is None:
                continue
            column = getattr(self.model, field)
            statement = statement.where(column == value)
        return statement
