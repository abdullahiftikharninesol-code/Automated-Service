"""Add generic qualification engine tables and lead fields.

Revision ID: 20261020_0007
Revises: 20261020_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261020_0007"
down_revision: str | None = "20261020_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create qualification_fields table
    op.create_table(
        "qualification_fields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("field_type", sa.String(length=32), nullable=False, server_default="TEXT"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("question_text", sa.Text(), nullable=True),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("example_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_qualification_fields_organization_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "key", name="uq_qualification_fields_org_key"
        ),
    )
    op.create_index(
        "ix_qualification_fields_org_order",
        "qualification_fields",
        ["organization_id", "enabled", "sort_order"],
    )
    op.create_index(
        "ix_qualification_fields_organization_id",
        "qualification_fields",
        ["organization_id"],
    )

    # 2. Add qualification columns to leads table
    op.add_column(
        "leads",
        sa.Column(
            "qualification_status",
            sa.String(length=32),
            nullable=False,
            server_default="NOT_STARTED",
        ),
    )
    op.add_column(
        "leads",
        sa.Column(
            "qualifications",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "leads",
        sa.Column("qualification_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column(
            "qualification_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_leads_org_qualification_status",
        "leads",
        ["organization_id", "qualification_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_leads_org_qualification_status", table_name="leads")
    op.drop_column("leads", "qualification_metadata")
    op.drop_column("leads", "qualification_completed_at")
    op.drop_column("leads", "qualifications")
    op.drop_column("leads", "qualification_status")

    op.drop_index("ix_qualification_fields_organization_id", table_name="qualification_fields")
    op.drop_index("ix_qualification_fields_org_order", table_name="qualification_fields")
    op.drop_table("qualification_fields")
