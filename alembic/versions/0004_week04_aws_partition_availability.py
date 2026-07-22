"""Add week 4 cloud partitions and availability target scope.

Revision ID: 0004_week04_aws_partition_availability
Revises: 0003_week03_parsing_models
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_week04_aws_partition_availability"
down_revision: str | None = "0003_week03_parsing_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PRODUCT_FAMILY_VALUES = (
    "'ecs_instance_family', 'obs_storage_class', "
    "'aws_ec2_instance_family', 'aws_s3_storage_class'"
)


def upgrade() -> None:
    op.create_table(
        "cloud_partition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("partition_code", sa.String(length=64), nullable=False),
        sa.Column("partition_name", sa.String(length=128), nullable=False),
        sa.Column("market_mode", sa.String(length=32), nullable=False),
        sa.Column("geography_scope", sa.String(length=256), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "market_mode IN ('domestic', 'international')",
            name="cloud_partition_market_mode",
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["provider.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_id",
            "partition_code",
            name="uq_cloud_partition_provider_code",
        ),
    )
    op.create_index("ix_cloud_partition_provider_id", "cloud_partition", ["provider_id"])
    op.create_index(
        "ix_cloud_partition_partition_code", "cloud_partition", ["partition_code"]
    )

    with op.batch_alter_table("source_document") as batch_op:
        batch_op.add_column(sa.Column("cloud_partition", sa.String(length=64), nullable=True))

    with op.batch_alter_table("region") as batch_op:
        batch_op.add_column(sa.Column("cloud_partition_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_region_cloud_partition_id", ["cloud_partition_id"])
        batch_op.create_foreign_key(
            "fk_region_cloud_partition_id_cloud_partition",
            "cloud_partition",
            ["cloud_partition_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("availability") as batch_op:
        batch_op.drop_constraint("uq_availability_product_region", type_="unique")
        batch_op.add_column(sa.Column("cloud_partition_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "target_type",
                sa.String(length=64),
                nullable=False,
                server_default="product",
            )
        )
        batch_op.add_column(
            sa.Column(
                "target_code",
                sa.String(length=256),
                nullable=False,
                server_default="product",
            )
        )
        batch_op.create_index("ix_availability_cloud_partition_id", ["cloud_partition_id"])
        batch_op.create_foreign_key(
            "fk_availability_cloud_partition_id_cloud_partition",
            "cloud_partition",
            ["cloud_partition_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_availability_product_region_target",
            ["product_id", "region_id", "target_type", "target_code"],
        )

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
            "family_type IN ('ecs_instance_family', 'obs_storage_class')",
        )

    with op.batch_alter_table("availability") as batch_op:
        batch_op.drop_constraint("uq_availability_product_region_target", type_="unique")
        batch_op.drop_constraint(
            "fk_availability_cloud_partition_id_cloud_partition",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_availability_cloud_partition_id")
        batch_op.drop_column("target_code")
        batch_op.drop_column("target_type")
        batch_op.drop_column("cloud_partition_id")
        batch_op.create_unique_constraint(
            "uq_availability_product_region",
            ["product_id", "region_id"],
        )

    with op.batch_alter_table("region") as batch_op:
        batch_op.drop_constraint("fk_region_cloud_partition_id_cloud_partition", type_="foreignkey")
        batch_op.drop_index("ix_region_cloud_partition_id")
        batch_op.drop_column("cloud_partition_id")

    with op.batch_alter_table("source_document") as batch_op:
        batch_op.drop_column("cloud_partition")

    op.drop_index("ix_cloud_partition_partition_code", table_name="cloud_partition")
    op.drop_index("ix_cloud_partition_provider_id", table_name="cloud_partition")
    op.drop_table("cloud_partition")
