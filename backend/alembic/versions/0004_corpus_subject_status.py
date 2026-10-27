"""corpus: subject_status, so images showing no subject (a whale on the watch corpus) leave the pool"""

revision = "0004"
down_revision = "0003"

import sqlalchemy as sa

from alembic import op

# keep in step with app/corpus/subject.py MIN_READABLE_SHARE
_BACKFILL = """
UPDATE corpus_items SET subject_status = (
    SELECT CASE WHEN SUM(a.value_json IS NOT NULL AND a.value_json != 'null') >= 0.25 * COUNT(*)
                THEN 'present' ELSE 'absent' END
    FROM corpus_attributes a WHERE a.item_id = corpus_items.id
)
WHERE EXISTS (SELECT 1 FROM corpus_attributes a WHERE a.item_id = corpus_items.id)
"""


def upgrade() -> None:
    op.add_column("corpus_items", sa.Column("subject_status", sa.String(), nullable=True))
    op.execute(_BACKFILL)


def downgrade() -> None:
    op.drop_column("corpus_items", "subject_status")
