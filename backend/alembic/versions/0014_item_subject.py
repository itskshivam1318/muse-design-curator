"""items remember the analysis subject: a short noun phrase naming the whole item"""

revision = "0014_item_subject"
down_revision = "0013_round3_plugins"

import sqlalchemy as sa

from alembic import op


def upgrade() -> None:
    with op.batch_alter_table("board_items", recreate="always") as b:
        b.add_column(sa.Column("subject", sa.String()))


def downgrade() -> None:
    with op.batch_alter_table("board_items", recreate="always") as b:
        b.drop_column("subject")
