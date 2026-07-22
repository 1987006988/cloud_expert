"""Add week 5 Aliyun zone availability models.

Revision ID: 0005_week05_aliyun_zone_availability
Revises: 0004_week04_aws_partition_availability
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_week05_aliyun_zone_availability"
down_revision: str | None = "0004_week04_aws_partition_availability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PRODUCT_FAMILY_VALUES = (
    "'ecs_instance_family', 'obs_storage_class', "
    "'aws_ec2_instance_family', 'aws_s3_storage_class', "
    "'aliyun_ecs_instance_family', 'aliyun_oss_storage_class'"
)


def upgrade() -> None:
    op.create_table(
        "availability_zone",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("cloud_partition_id", sa.Integer(), nullable=True),
        sa.Column("zone_code", sa.String(length=128), nullable=False),
        sa.Column("zone_name", sa.String(length=256), nullable=False),
        sa.Column("market_mode", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "market_mode IN ('domestic', 'international')",
            name="availability_zone_market_mode",
        ),
        sa.ForeignKeyConstraint(
            ["cloud_partition_id"], ["cloud_partition.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["provider_id"], ["provider.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "zone_code", name="uq_zone_provider_code"),
        sa.UniqueConstraint("region_id", "zone_code", name="uq_zone_region_code"),
    )
    op.create_index("ix_availability_zone_provider_id", "availability_zone", ["provider_id"])
    op.create_index("ix_availability_zone_region_id", "availability_zone", ["region_id"])
    op.create_index(
        "ix_availability_zone_cloud_partition_id",
        "availability_zone",
        ["cloud_partition_id"],
    )
    op.create_index("ix_availability_zone_evidence_id", "availability_zone", ["evidence_id"])

    op.create_table(
        "zone_availability",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("availability_zone_id", sa.Integer(), nullable=False),
        sa.Column("cloud_partition_id", sa.Integer(), nullable=True),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_code", sa.String(length=256), nullable=False),
        sa.Column("availability_status", sa.String(length=32), nullable=False),
        sa.Column("public_preview", sa.Boolean(), nullable=False),
        sa.Column("generally_available", sa.Boolean(), nullable=False),
        sa.Column("available_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unavailable_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "availability_status IN "
            "('available', 'preview', 'limited', 'unavailable', 'unknown', 'retired')",
            name="zone_availability_status",
        ),
        sa.CheckConstraint(
            "availability_status NOT IN ('available', 'preview', 'limited') "
            "OR evidence_id IS NOT NULL",
            name="zone_availability_positive_requires_evidence",
        ),
        sa.CheckConstraint(
            "unavailable_since IS NULL OR available_since IS NULL "
            "OR unavailable_since >= available_since",
            name="zone_availability_time_range",
        ),
        sa.ForeignKeyConstraint(
            ["availability_zone_id"],
            ["availability_zone.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cloud_partition_id"], ["cloud_partition.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "availability_zone_id",
            "target_type",
            "target_code",
            name="uq_zone_availability_product_zone_target",
        ),
    )
    op.create_index("ix_zone_availability_product_id", "zone_availability", ["product_id"])
    op.create_index("ix_zone_availability_region_id", "zone_availability", ["region_id"])
    op.create_index(
        "ix_zone_availability_availability_zone_id",
        "zone_availability",
        ["availability_zone_id"],
    )
    op.create_index(
        "ix_zone_availability_cloud_partition_id",
        "zone_availability",
        ["cloud_partition_id"],
    )
    op.create_index("ix_zone_availability_evidence_id", "zone_availability", ["evidence_id"])

    with op.batch_alter_table("product_family") as batch_op:
        batch_op.drop_constraint("product_family_type", type_="check")
        batch_op.create_check_constraint(
            "product_family_type",
            f"family_type IN ({PRODUCT_FAMILY_VALUES})",
        )


def downgrade() -> None:
    with op.batch_alter_table("product_family") as batch_op:
        batch_op.drop_constraint("product_family_type", type_="check")
        batch_op.create_check_constraint(
            "product_family_type",
            "family_type IN ('ecs_instance_family', 'obs_storage_class', "
            "'aws_ec2_instance_family', 'aws_s3_storage_class')",
        )

    op.drop_index("ix_zone_availability_evidence_id", table_name="zone_availability")
    op.drop_index("ix_zone_availability_cloud_partition_id", table_name="zone_availability")
    op.drop_index("ix_zone_availability_availability_zone_id", table_name="zone_availability")
    op.drop_index("ix_zone_availability_region_id", table_name="zone_availability")
    op.drop_index("ix_zone_availability_product_id", table_name="zone_availability")
    op.drop_table("zone_availability")

    op.drop_index("ix_availability_zone_evidence_id", table_name="availability_zone")
    op.drop_index("ix_availability_zone_cloud_partition_id", table_name="availability_zone")
    op.drop_index("ix_availability_zone_region_id", table_name="availability_zone")
    op.drop_index("ix_availability_zone_provider_id", table_name="availability_zone")
    op.drop_table("availability_zone")
