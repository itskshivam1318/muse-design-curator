"""round 3 plugins: model items, option flag on items, fal job state on runs"""

revision = "0013_round3_plugins"
down_revision = "0012_board_chat"

import sqlalchemy as sa

from alembic import op

OLD = "kind IN ('image', 'video', 'link', 'note')"
NEW = "kind IN ('image', 'video', 'link', 'note', 'model')"


def upgrade() -> None:
    with op.batch_alter_table("board_items", recreate="always") as b:
        b.add_column(sa.Column("option_run_id", sa.String()))
        b.create_index("ix_board_items_option_run_id", ["option_run_id"])
        b.drop_constraint("ck_item_kind", type_="check")
        b.create_check_constraint("ck_item_kind", NEW)
    with op.batch_alter_table("plugin_runs", recreate="always") as b:
        b.add_column(sa.Column("external_json", sa.JSON()))


def downgrade() -> None:
    with op.batch_alter_table("plugin_runs", recreate="always") as b:
        b.drop_column("external_json")
    # model items (and their dependents) cannot exist under the old kind check
    models = "SELECT id FROM board_items WHERE kind = 'model'"
    for table in ("item_frames", "item_attributes", "attribute_events"):
        op.execute(f"DELETE FROM {table} WHERE item_id IN ({models})")
    op.execute(f"UPDATE board_items SET parent_item_id = NULL WHERE parent_item_id IN ({models})")
    op.execute(
        f"UPDATE board_items SET put_source_item_id = NULL WHERE put_source_item_id IN ({models})"
    )
    op.execute("DELETE FROM board_items WHERE kind = 'model'")
    with op.batch_alter_table("board_items", recreate="always") as b:
        b.drop_index("ix_board_items_option_run_id")
        b.drop_column("option_run_id")
        b.drop_constraint("ck_item_kind", type_="check")
        b.create_check_constraint("ck_item_kind", OLD)
