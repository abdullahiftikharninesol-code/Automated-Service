"""Initial product schema.

Revision ID: 20261001_0001
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261001_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    role = sa.Enum("OWNER", "MEMBER", name="userrole")
    source = sa.Enum("WEBSITE", "EMAIL", "PHONE", "MANUAL", name="leadsource")
    lead_status = sa.Enum("NEW", "CONTACTED", "BOOKED", "LOST", name="leadstatus")
    urgency = sa.Enum("LOW", "NORMAL", "HIGH", "EMERGENCY", name="urgency")
    event_type = sa.Enum(
        "LEAD_CREATED",
        "AI_PROCESSED",
        "ACKNOWLEDGEMENT_GENERATED",
        "ACKNOWLEDGEMENT_SENT",
        "FOLLOWUP_SCHEDULED",
        "FOLLOWUP_GENERATED",
        "STATUS_CHANGED",
        "NOTE_ADDED",
        name="leadeventtype",
    )
    followup_status = sa.Enum("PENDING", "COMPLETED", "CANCELLED", name="followupstatus")
    followup_channel = sa.Enum("EMAIL", "INTERNAL", name="followupchannel")

    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("industry", sa.String(80), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("followup_new_lead_minutes", sa.Integer(), nullable=False),
        sa.Column("followup_second_reminder_hours", sa.Integer(), nullable=False),
        sa.Column("followup_contacted_hours", sa.Integer(), nullable=False),
        sa.Column("followup_final_days", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_organization_id", "users", ["organization_id"])
    op.create_table(
        "leads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("customer_name", sa.String(160), nullable=False),
        sa.Column("customer_email", sa.String(320)),
        sa.Column("customer_phone", sa.String(60)),
        sa.Column("service_type", sa.String(160)),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("location", sa.String(255)),
        sa.Column("urgency", urgency, nullable=False),
        sa.Column("preferred_date", sa.Date()),
        sa.Column("preferred_time", sa.Time()),
        sa.Column("preferred_date_text", sa.String(80)),
        sa.Column("preferred_time_text", sa.String(80)),
        sa.Column("source", source, nullable=False),
        sa.Column("status", lead_status, nullable=False),
        sa.Column("ai_summary", sa.Text()),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True)),
        sa.Column("next_followup_at", sa.DateTime(timezone=True)),
        sa.Column("booked_at", sa.DateTime(timezone=True)),
        sa.Column("lost_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_leads_organization_id", "leads", ["organization_id"])
    op.create_index(
        "ix_leads_org_status_created",
        "leads",
        ["organization_id", "status", "created_at"],
    )
    op.create_index("ix_leads_org_followup", "leads", ["organization_id", "next_followup_at"])
    op.create_table(
        "lead_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_events_lead_id", "lead_events", ["lead_id"])
    op.create_index("ix_lead_events_organization_id", "lead_events", ["organization_id"])
    op.create_index("ix_lead_events_org_lead", "lead_events", ["organization_id", "lead_id"])
    op.create_table(
        "followups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", followup_status, nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("channel", followup_channel, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_followups_lead_id", "followups", ["lead_id"])
    op.create_index("ix_followups_organization_id", "followups", ["organization_id"])
    op.create_index(
        "ix_followups_org_status_scheduled",
        "followups",
        ["organization_id", "status", "scheduled_for"],
    )


def downgrade() -> None:
    op.drop_table("followups")
    op.drop_table("lead_events")
    op.drop_table("leads")
    op.drop_table("users")
    op.drop_table("organizations")
    for enum_name in (
        "followupchannel",
        "followupstatus",
        "leadeventtype",
        "urgency",
        "leadstatus",
        "leadsource",
        "userrole",
    ):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
