"""living board: flower hub offsets, undocked takes"""

revision = "0009_living_board"
down_revision = "0008_item_analysis"

import sqlalchemy as sa

from alembic import op


def upgrade() -> None:
    with op.batch_alter_table("explorations", recreate="always") as b:
        b.add_column(sa.Column("dx", sa.Float()))
        b.add_column(sa.Column("dy", sa.Float()))
    with op.batch_alter_table("explore_options", recreate="always") as b:
        b.add_column(sa.Column("undocked", sa.Boolean(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("explore_options", recreate="always") as b:
        b.drop_column("undocked")
    with op.batch_alter_table("explorations", recreate="always") as b:
        b.drop_column("dy")
        b.drop_column("dx")
