"""ui_events: what the person did in the board UI"""

revision = "0005"
down_revision = "0004"

import sqlalchemy as sa

from alembic import op


def upgrade() -> None:
    op.create_table(
        "ui_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("board_id", sa.String(), sa.ForeignKey("boards.id"), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=True),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("detail_json", sa.JSON(), nullable=True),
        sa.Column("client_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_ui_events_board_id", "ui_events", ["board_id"])


def downgrade() -> None:
    op.drop_index("ix_ui_events_board_id", "ui_events")
    op.drop_table("ui_events")
