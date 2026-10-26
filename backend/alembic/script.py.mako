"""${message}"""
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}

import sqlalchemy as sa
from alembic import op

def upgrade() -> None:
    ${upgrades if upgrades else "pass"}
