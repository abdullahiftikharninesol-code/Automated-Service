"""Add generic inbound capture.

Revision ID: 20261002_0002
Revises: 20261001_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261002_0002"
down_revision: str | None = "20261001_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BUSINESS_TYPES = (
    "GENERAL",
    "HVAC",
    "ECOMMERCE",
    "CLOTHING",
    "DENTAL",
    "REAL_ESTATE",
    "AGENCY",
    "HOME_SERVICES",
)
INBOUND_CHANNELS = (
    "WEBSITE_FORM",
    "WEBSITE_WEBHOOK",
    "EMAIL",
    "WHATSAPP",
    "PHONE",
    "MANUAL",
    "CHAT_WIDGET",
)


def _enum(name: str, values: tuple[str, ...]) -> sa.Enum:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for value in ("WEBSITE_FORM", "WEBSITE_WEBHOOK", "WHATSAPP", "CHAT_WIDGET"):
            op.execute(f"ALTER TYPE leadsource ADD VALUE IF NOT EXISTS '{value}'")
        for value in (
            "INBOUND_MESSAGE_RECEIVED",
            "LEAD_ENRICHED",
            "ACKNOWLEDGEMENT_FAILED",
        ):
            op.execute(f"ALTER TYPE leadeventtype ADD VALUE IF NOT EXISTS '{value}'")

    business_type = _enum("businesstype", BUSINESS_TYPES)
    inbound_channel = _enum("inboundchannel", INBOUND_CHANNELS)

    op.add_column(
        "organizations",
        sa.Column(
            "business_type",
            business_type,
            nullable=False,
            server_default="GENERAL",
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("duplicate_window_minutes", sa.Integer(), nullable=False, server_default="60"),
    )
    op.execute("UPDATE organizations SET business_type = 'HVAC' WHERE UPPER(industry) = 'HVAC'")

    op.add_column("leads", sa.Column("intent", sa.String(80), nullable=True))
    op.add_column("leads", sa.Column("category_or_service", sa.String(160), nullable=True))
    op.add_column("leads", sa.Column("product_name", sa.String(160), nullable=True))
    op.add_column("leads", sa.Column("product_variant", sa.String(160), nullable=True))
    op.add_column("leads", sa.Column("quantity", sa.Integer(), nullable=True))
    op.add_column(
        "leads",
        sa.Column(
            "ai_additional_fields",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.execute("UPDATE leads SET category_or_service = service_type")

    op.create_table(
        "inbound_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("channel", inbound_channel, nullable=False),
        sa.Column("external_message_id", sa.String(255), nullable=True),
        sa.Column("customer_name", sa.String(160), nullable=False),
        sa.Column("customer_email", sa.String(320), nullable=True),
        sa.Column("customer_phone", sa.String(60), nullable=True),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "channel",
            "external_message_id",
            name="uq_inbound_messages_external",
        ),
    )
    op.create_index(
        "ix_inbound_messages_organization_id",
        "inbound_messages",
        ["organization_id"],
    )
    op.create_index("ix_inbound_messages_lead_id", "inbound_messages", ["lead_id"])
    op.create_index(
        "ix_inbound_messages_org_received",
        "inbound_messages",
        ["organization_id", "received_at"],
    )
    op.create_index(
        "ix_inbound_messages_org_lead",
        "inbound_messages",
        ["organization_id", "lead_id"],
    )


def downgrade() -> None:
    op.drop_table("inbound_messages")
    for column in (
        "ai_additional_fields",
        "quantity",
        "product_variant",
        "product_name",
        "category_or_service",
        "intent",
    ):
        op.drop_column("leads", column)
    op.drop_column("organizations", "duplicate_window_minutes")
    op.drop_column("organizations", "business_type")

    bind = op.get_bind()
    sa.Enum(name="inboundchannel").drop(bind, checkfirst=True)
    sa.Enum(name="businesstype").drop(bind, checkfirst=True)
