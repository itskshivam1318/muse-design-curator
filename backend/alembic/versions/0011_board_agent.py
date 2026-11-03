"""board agent: agent runs and their recorded steps"""

revision = "0011_board_agent"
down_revision = "0010_put_into"

import sqlalchemy as sa

from alembic import op


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("board_id", sa.String(), sa.ForeignKey("boards.id"), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("goal", sa.String(), nullable=False),
        sa.Column("deliverables_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON()),
        sa.Column("finish_refusals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.String()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint("source IN ('mcp', 'muse')", name="ck_agent_run_source"),
        sa.CheckConstraint(
            "status IN ('running', 'needs_input', 'done', 'paused')", name="ck_agent_run_status"
        ),
    )
    op.create_index("ix_agent_runs_board_id", "agent_runs", ["board_id"])
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("board_id", sa.String(), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(), nullable=False),
        sa.Column("args_json", sa.JSON(), nullable=False),
        sa.Column("say", sa.String()),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("result_json", sa.JSON()),
        sa.Column("item_ids_json", sa.JSON(), nullable=False),
        sa.Column("highlight", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_agent_steps_run_id", "agent_steps", ["run_id"])
    op.create_index("ix_agent_steps_board_id", "agent_steps", ["board_id"])
    op.create_index("ix_agent_steps_board_created", "agent_steps", ["board_id", "created_at"])


def downgrade() -> None:
    op.drop_table("agent_steps")
    op.drop_table("agent_runs")
