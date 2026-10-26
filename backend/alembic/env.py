from alembic import context
from app.config import get_settings
from app.db import models
from app.db.session import make_engine_from_settings

target_metadata = models.Base.metadata


def run() -> None:
    connection = context.config.attributes.get("connection")
    if connection is None:
        engine = make_engine_from_settings(get_settings())
        with engine.begin() as conn:
            context.configure(connection=conn, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
        return
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


run()
