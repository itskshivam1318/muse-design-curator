"""put into: a result picture keeps the picture put into it"""

revision = "0010_put_into"
down_revision = "0009_living_board"

import sqlalchemy as sa

from alembic import op


def upgrade() -> None:
    with op.batch_alter_table("board_items", recreate="always") as b:
        b.add_column(
            sa.Column(
                "put_source_item_id",
                sa.String(),
                sa.ForeignKey("board_items.id", name="fk_board_items_put_source_item_id"),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("board_items", recreate="always") as b:
        b.drop_column("put_source_item_id")
