from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin, TimestampMixin

if TYPE_CHECKING:
    from cloud_expert.database.models.product import Product
    from cloud_expert.database.models.region import Region


class Provider(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False, default="public_cloud")
    official_website: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    products: Mapped[list["Product"]] = relationship(back_populates="provider")
    regions: Mapped[list["Region"]] = relationship(back_populates="provider")
