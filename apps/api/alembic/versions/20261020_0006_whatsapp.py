"""Add WhatsApp organization configuration fields.

Revision ID: 20261020_0006
Revises: 20261016_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261020_0006"
down_revision: str | None = "20261016_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "whatsapp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("whatsapp_phone_number_id", sa.String(50), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("whatsapp_business_account_id", sa.String(50), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("whatsapp_display_phone_number", sa.String(30), nullable=True),
    )
    op.create_index(
        "ix_organizations_whatsapp_phone_number_id",
        "organizations",
        ["whatsapp_phone_number_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_organizations_whatsapp_phone_number_id", table_name="organizations")
    op.drop_column("organizations", "whatsapp_display_phone_number")
    op.drop_column("organizations", "whatsapp_business_account_id")
    op.drop_column("organizations", "whatsapp_phone_number_id")
    op.drop_column("organizations", "whatsapp_enabled")
