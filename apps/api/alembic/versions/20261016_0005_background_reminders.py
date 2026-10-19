"""Add background jobs and reminder engine fields.

Revision ID: 20261016_0005
Revises: 20261016_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261016_0005"
down_revision: str | None = "20261016_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FOLLOWUP_TYPES = ("OWNER_RESPONSE_REMINDER", "LEAD_FOLLOWUP")


def _enum(name: str, values: tuple[str, ...]) -> sa.Enum:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # 1. Extend followupstatus enum
        for val in ("PROCESSING", "FAILED"):
            op.execute(f"ALTER TYPE followupstatus ADD VALUE IF NOT EXISTS '{val}'")

        # 2. Extend leadeventtype enum
        for val in (
            "OWNER_REMINDER_SCHEDULED",
            "OWNER_REMINDER_SENT",
            "OWNER_REMINDER_CANCELLED",
            "OWNER_REMINDER_FAILED",
        ):
            op.execute(f"ALTER TYPE leadeventtype ADD VALUE IF NOT EXISTS '{val}'")

    followup_type_enum = _enum("followuptype", FOLLOWUP_TYPES)

    # 3. Add organization owner reminder settings
    op.add_column(
        "organizations",
        sa.Column(
            "owner_reminder_delay_minutes", sa.Integer(), nullable=False, server_default="60"
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "owner_reminder_repeat_minutes", sa.Integer(), nullable=False, server_default="60"
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("owner_reminder_max_attempts", sa.Integer(), nullable=False, server_default="3"),
    )

    # 4. Alter followups table
    op.alter_column("followups", "scheduled_for", new_column_name="due_at")
    op.add_column(
        "followups",
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_followups_conversation_id",
        "followups",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "followups",
        sa.Column("type", followup_type_enum, nullable=False, server_default="LEAD_FOLLOWUP"),
    )
    op.add_column(
        "followups",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "followups",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "followups",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "followups",
        sa.Column("failure_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "followups",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # Backfill processed_at from completed_at where present
    op.execute("UPDATE followups SET processed_at = completed_at WHERE completed_at IS NOT NULL")

    # Update indexes
    op.drop_index("ix_followups_org_status_scheduled", table_name="followups")
    op.create_index(
        "ix_followups_org_status_due",
        "followups",
        ["organization_id", "status", "due_at"],
    )
    op.create_index(
        "ix_followups_status_due",
        "followups",
        ["status", "due_at"],
    )
    op.create_index(
        "ix_followups_conv_id",
        "followups",
        ["conversation_id"],
    )


def downgrade() -> None:
    # 1. Revert followups indexes
    op.drop_index("ix_followups_conv_id", table_name="followups")
    op.drop_index("ix_followups_status_due", table_name="followups")
    op.drop_index("ix_followups_org_status_due", table_name="followups")
    op.create_index(
        "ix_followups_org_status_scheduled",
        "followups",
        ["organization_id", "status", "due_at"],
    )

    # 2. Revert followups columns
    op.drop_constraint("fk_followups_conversation_id", "followups", type_="foreignkey")
    op.drop_column("followups", "updated_at")
    op.drop_column("followups", "failure_reason")
    op.drop_column("followups", "processed_at")
    op.drop_column("followups", "last_attempt_at")
    op.drop_column("followups", "attempt_count")
    op.drop_column("followups", "type")
    op.drop_column("followups", "conversation_id")
    op.alter_column("followups", "due_at", new_column_name="scheduled_for")

    # 3. Revert organizations columns
    op.drop_column("organizations", "owner_reminder_max_attempts")
    op.drop_column("organizations", "owner_reminder_repeat_minutes")
    op.drop_column("organizations", "owner_reminder_delay_minutes")

    # 4. Drop followuptype enum if postgresql
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS followuptype")
