"""runs: progress heartbeat and the demo visitor charged for the run"""

revision = "0003"
down_revision = "0002"

import sqlalchemy as sa

from alembic import op


def upgrade() -> None:
    op.add_column("variation_runs", sa.Column("updated_at", sa.String(), nullable=True))
    op.add_column("variation_runs", sa.Column("client_ip", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("variation_runs", "client_ip")
    op.drop_column("variation_runs", "updated_at")
