"""Add foundation hardening (normalized phone, webhook secret, default phone region).

Revision ID: 20261015_0003
Revises: 20261002_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261015_0003"
down_revision: str | None = "20261002_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("default_phone_region", sa.String(10), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("inbound_webhook_secret", sa.String(255), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("customer_phone_normalized", sa.String(60), nullable=True),
    )
    op.create_index(
        "ix_leads_org_phone_norm",
        "leads",
        ["organization_id", "customer_phone_normalized"],
    )
    op.add_column(
        "inbound_messages",
        sa.Column("customer_phone_normalized", sa.String(60), nullable=True),
    )
    op.create_index(
        "ix_inbound_messages_org_phone_norm",
        "inbound_messages",
        ["organization_id", "customer_phone_normalized"],
    )


def downgrade() -> None:
    op.drop_index("ix_inbound_messages_org_phone_norm", table_name="inbound_messages")
    op.drop_column("inbound_messages", "customer_phone_normalized")
    op.drop_index("ix_leads_org_phone_norm", table_name="leads")
    op.drop_column("leads", "customer_phone_normalized")
    op.drop_column("organizations", "inbound_webhook_secret")
    op.drop_column("organizations", "default_phone_region")
