"""Add Customer, Conversation, and ConversationMessage models with backfill.

Revision ID: 20261016_0004
Revises: 20261015_0003
"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261016_0004"
down_revision: str | None = "20261015_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INBOUND_CHANNELS = (
    "WEBSITE_FORM",
    "WEBSITE_WEBHOOK",
    "EMAIL",
    "WHATSAPP",
    "PHONE",
    "MANUAL",
    "CHAT_WIDGET",
    "INSTAGRAM",
    "FACEBOOK",
)
CONVERSATION_STATUSES = ("OPEN", "CLOSED", "ARCHIVED")
WAITING_ON = ("OWNER", "CUSTOMER", "SYSTEM", "NONE")
MESSAGE_DIRECTIONS = ("INBOUND", "OUTBOUND")
MESSAGE_SENDER_TYPES = ("CUSTOMER", "OWNER", "SYSTEM", "AI")
MESSAGE_DELIVERY_STATUSES = ("PENDING", "SENT", "DELIVERED", "READ", "FAILED")


def _enum(name: str, values: tuple[str, ...]) -> sa.Enum:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for value in ("INSTAGRAM", "FACEBOOK"):
            op.execute(f"ALTER TYPE inboundchannel ADD VALUE IF NOT EXISTS '{value}'")

    channel_enum = _enum("inboundchannel", INBOUND_CHANNELS)
    status_enum = _enum("conversationstatus", CONVERSATION_STATUSES)
    waiting_on_enum = _enum("waitingon", WAITING_ON)
    direction_enum = _enum("messagedirection", MESSAGE_DIRECTIONS)
    sender_type_enum = _enum("messagesendertype", MESSAGE_SENDER_TYPES)
    delivery_status_enum = _enum("messagedeliverystatus", MESSAGE_DELIVERY_STATUSES)

    # 1. Create customers table
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("email_normalized", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(60), nullable=True),
        sa.Column("phone_normalized", sa.String(60), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customers_org", "customers", ["organization_id"])
    op.create_index(
        "ix_customers_org_email_norm", "customers", ["organization_id", "email_normalized"]
    )
    op.create_index(
        "ix_customers_org_phone_norm", "customers", ["organization_id", "phone_normalized"]
    )

    # 2. Create conversations table
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("channel", channel_enum, nullable=False),
        sa.Column("status", status_enum, nullable=False),
        sa.Column("waiting_on", waiting_on_enum, nullable=False),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column("external_thread_id", sa.String(255), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_org_status", "conversations", ["organization_id", "status"])
    op.create_index(
        "ix_conversations_org_customer", "conversations", ["organization_id", "customer_id"]
    )
    op.create_index("ix_conversations_org_lead", "conversations", ["organization_id", "lead_id"])
    op.create_index(
        "ix_conversations_org_last_msg", "conversations", ["organization_id", "last_message_at"]
    )

    # 3. Create conversation_messages table
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("direction", direction_enum, nullable=False),
        sa.Column("channel", channel_enum, nullable=False),
        sa.Column("sender_type", sender_type_enum, nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("external_message_id", sa.String(255), nullable=True),
        sa.Column("delivery_status", delivery_status_enum, nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "channel",
            "external_message_id",
            name="uq_conv_messages_external",
        ),
    )
    op.create_index(
        "ix_conv_messages_org_conv",
        "conversation_messages",
        ["organization_id", "conversation_id"],
    )
    op.create_index(
        "ix_conv_messages_sent", "conversation_messages", ["conversation_id", "sent_at"]
    )

    # 4. Add columns to leads table
    op.add_column("leads", sa.Column("customer_id", sa.Uuid(), nullable=True))
    op.add_column("leads", sa.Column("primary_conversation_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_leads_customer_id",
        "leads",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_leads_primary_conv_id",
        "leads",
        "conversations",
        ["primary_conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_leads_customer_id", "leads", ["customer_id"])
    op.create_index("ix_leads_primary_conv_id", "leads", ["primary_conversation_id"])

    # 5. Safe historical backfill
    _backfill_historical_data(bind)


def _backfill_historical_data(bind: sa.engine.Connection) -> None:
    # Read existing leads
    leads_res = bind.execute(
        sa.text(
            "SELECT id, organization_id, customer_name, customer_email, customer_phone, "
            "customer_phone_normalized, message, source, status, created_at FROM leads"
        )
    ).fetchall()

    lead_conv_map: dict[uuid.UUID, uuid.UUID] = {}

    for row in leads_res:
        lead_id = row[0]
        org_id = row[1]
        name = row[2]
        email = row[3]
        phone = row[4]
        phone_norm = row[5]
        source = row[7] or "WEBSITE_FORM"
        status = row[8] or "NEW"
        created_at = row[9]

        email_norm = email.strip().lower() if email else None

        # Check existing customer in this org
        cust_row = None
        if phone_norm:
            cust_row = bind.execute(
                sa.text(
                    "SELECT id FROM customers WHERE organization_id = :org_id "
                    "AND phone_normalized = :p"
                ),
                {"org_id": org_id, "p": phone_norm},
            ).fetchone()
        if not cust_row and email_norm:
            cust_row = bind.execute(
                sa.text(
                    "SELECT id FROM customers WHERE organization_id = :org_id "
                    "AND email_normalized = :e"
                ),
                {"org_id": org_id, "e": email_norm},
            ).fetchone()

        if cust_row:
            cust_id = cust_row[0]
        else:
            cust_id = uuid.uuid4()
            bind.execute(
                sa.text(
                    "INSERT INTO customers (id, organization_id, name, email, email_normalized, "
                    "phone, phone_normalized, metadata, created_at, updated_at) "
                    "VALUES (:id, :org_id, :name, :email, :email_norm, :phone, :phone_norm, "
                    ":meta, :created_at, :updated_at)"
                ),
                {
                    "id": cust_id,
                    "org_id": org_id,
                    "name": name,
                    "email": email,
                    "email_norm": email_norm,
                    "phone": phone,
                    "phone_norm": phone_norm,
                    "meta": json.dumps({}),
                    "created_at": created_at,
                    "updated_at": created_at,
                },
            )

        # Map channel
        channel_val = source if source in INBOUND_CHANNELS else "WEBSITE_FORM"
        conv_status = "OPEN" if status in ("NEW", "CONTACTED") else "CLOSED"
        waiting_on = "OWNER" if status in ("NEW", "CONTACTED") else "NONE"
        conv_id = uuid.uuid4()

        bind.execute(
            sa.text(
                "INSERT INTO conversations (id, organization_id, customer_id, lead_id, channel, "
                "status, waiting_on, last_message_at, last_inbound_at, created_at, updated_at) "
                "VALUES (:id, :org_id, :cust_id, :lead_id, :channel, :status, :waiting_on, "
                ":last_msg, :last_in, :created_at, :updated_at)"
            ),
            {
                "id": conv_id,
                "org_id": org_id,
                "cust_id": cust_id,
                "lead_id": lead_id,
                "channel": channel_val,
                "status": conv_status,
                "waiting_on": waiting_on,
                "last_msg": created_at,
                "last_in": created_at,
                "created_at": created_at,
                "updated_at": created_at,
            },
        )

        lead_conv_map[lead_id] = conv_id

        # Update lead with customer_id and primary_conversation_id
        bind.execute(
            sa.text(
                "UPDATE leads SET customer_id = :cust_id, primary_conversation_id = :conv_id "
                "WHERE id = :lead_id"
            ),
            {"cust_id": cust_id, "conv_id": conv_id, "lead_id": lead_id},
        )

    # Backfill inbound_messages into conversation_messages
    inbound_res = bind.execute(
        sa.text(
            "SELECT id, organization_id, lead_id, channel, external_message_id, customer_name, "
            "customer_email, customer_phone, message_text, metadata, received_at "
            "FROM inbound_messages"
        )
    ).fetchall()

    for msg in inbound_res:
        org_id = msg[1]
        lead_id = msg[2]
        channel = msg[3]
        ext_msg_id = msg[4]
        body = msg[8] or ""
        msg_meta = msg[9] if msg[9] is not None else {}
        received_at = msg[10]

        conv_id = lead_conv_map.get(lead_id)
        if not conv_id:
            continue

        meta_json = json.dumps(msg_meta) if isinstance(msg_meta, dict) else (msg_meta or "{}")
        bind.execute(
            sa.text(
                "INSERT INTO conversation_messages (id, organization_id, conversation_id, "
                "direction, channel, sender_type, body, external_message_id, delivery_status, "
                "metadata, sent_at, created_at) "
                "VALUES (:id, :org_id, :conv_id, 'INBOUND', :channel, 'CUSTOMER', :body, "
                ":ext_id, 'DELIVERED', :meta, :sent_at, :created_at)"
            ),
            {
                "id": uuid.uuid4(),
                "org_id": org_id,
                "conv_id": conv_id,
                "channel": channel,
                "body": body,
                "ext_id": ext_msg_id,
                "meta": meta_json,
                "sent_at": received_at,
                "created_at": received_at,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_leads_primary_conv_id", table_name="leads")
    op.drop_index("ix_leads_customer_id", table_name="leads")
    op.drop_constraint("fk_leads_primary_conv_id", "leads", type_="foreignkey")
    op.drop_constraint("fk_leads_customer_id", "leads", type_="foreignkey")
    op.drop_column("leads", "primary_conversation_id")
    op.drop_column("leads", "customer_id")

    op.drop_table("conversation_messages")
    op.drop_table("conversations")
    op.drop_table("customers")
