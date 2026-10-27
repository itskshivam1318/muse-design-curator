"""live search: corpus index depth, whole-image palette, run candidate origin"""

revision = "0002"
down_revision = "0001"

import sqlalchemy as sa

from alembic import op


def upgrade() -> None:
    op.add_column("corpus_items", sa.Column("index_depth", sa.String(), nullable=True))
    op.add_column("corpus_items", sa.Column("palette_json", sa.JSON(), nullable=True))
    op.add_column("run_candidates", sa.Column("origin", sa.String(), nullable=True))
    op.execute("UPDATE corpus_items SET index_depth = 'full' WHERE indexing_status = 'indexed'")


def downgrade() -> None:
    op.drop_column("run_candidates", "origin")
    op.drop_column("corpus_items", "palette_json")
    op.drop_column("corpus_items", "index_depth")
