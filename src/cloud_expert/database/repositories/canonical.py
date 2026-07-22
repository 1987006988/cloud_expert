from sqlalchemy import select

from cloud_expert.database.models.canonical import (
    CanonicalFieldDefinition,
    ComparabilityAssessment,
    NormalizationRule,
    NormalizedSpecification,
)
from cloud_expert.database.repositories.base import BaseRepository


class CanonicalFieldDefinitionRepository(BaseRepository[CanonicalFieldDefinition]):
    model = CanonicalFieldDefinition

    def get_by_code(self, code: str) -> CanonicalFieldDefinition | None:
        return self.session.scalar(select(CanonicalFieldDefinition).where(self.model.code == code))

    def list_active(self) -> list[CanonicalFieldDefinition]:
        return list(
            self.session.scalars(
                select(CanonicalFieldDefinition)
                .where(CanonicalFieldDefinition.is_active.is_(True))
                .order_by(CanonicalFieldDefinition.code)
            ).all()
        )


class NormalizationRuleRepository(BaseRepository[NormalizationRule]):
    model = NormalizationRule

    def get_by_code_version(self, code: str, version: str) -> NormalizationRule | None:
        return self.session.scalar(
            select(NormalizationRule).where(
                NormalizationRule.code == code,
                NormalizationRule.version == version,
            )
        )

    def list_active(self) -> list[NormalizationRule]:
        return list(
            self.session.scalars(
                select(NormalizationRule)
                .where(NormalizationRule.is_active.is_(True))
                .order_by(NormalizationRule.code)
            ).all()
        )


class NormalizedSpecificationRepository(BaseRepository[NormalizedSpecification]):
    model = NormalizedSpecification

    def list_by_product(self, product_id: int) -> list[NormalizedSpecification]:
        return list(
            self.session.scalars(
                select(NormalizedSpecification)
                .where(NormalizedSpecification.product_id == product_id)
                .order_by(NormalizedSpecification.id)
            ).all()
        )

    def list_by_canonical_field(self, canonical_field_id: int) -> list[NormalizedSpecification]:
        return list(
            self.session.scalars(
                select(NormalizedSpecification)
                .where(NormalizedSpecification.canonical_field_id == canonical_field_id)
                .order_by(NormalizedSpecification.id)
            ).all()
        )


class ComparabilityAssessmentRepository(BaseRepository[ComparabilityAssessment]):
    model = ComparabilityAssessment

    def list_for_product(self, product_id: int) -> list[ComparabilityAssessment]:
        return list(
            self.session.scalars(
                select(ComparabilityAssessment)
                .where(
                    (ComparabilityAssessment.source_product_id == product_id)
                    | (ComparabilityAssessment.target_product_id == product_id)
                )
                .order_by(ComparabilityAssessment.id)
            ).all()
        )
