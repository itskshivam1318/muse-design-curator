"""board chat: messages, the run's model history, and the waiting status"""

revision = "0012_board_chat"
down_revision = "0011_board_agent"

import sqlalchemy as sa

from alembic import op

OLD = "status IN ('running', 'needs_input', 'done', 'paused')"
NEW = "status IN ('running', 'needs_input', 'waiting', 'done', 'paused')"


def upgrade() -> None:
    with op.batch_alter_table("agent_runs", recreate="always") as b:
        b.add_column(sa.Column("history_json", sa.JSON()))
        b.drop_constraint("ck_agent_run_status", type_="check")
        b.create_check_constraint("ck_agent_run_status", NEW)
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("board_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("data_json", sa.JSON()),
        sa.Column("answered", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint("role IN ('person', 'agent', 'question')", name="ck_agent_message_role"),
    )
    op.create_index("ix_agent_messages_run_id", "agent_messages", ["run_id"])


def downgrade() -> None:
    op.drop_table("agent_messages")
    op.execute("UPDATE agent_runs SET status = 'paused' WHERE status = 'waiting'")
    with op.batch_alter_table("agent_runs", recreate="always") as b:
        b.drop_constraint("ck_agent_run_status", type_="check")
        b.create_check_constraint("ck_agent_run_status", OLD)
        b.drop_column("history_json")
