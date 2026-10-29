"""round 2: notes, staged takes, kept options, plugin tables"""

revision = "0007_round2"
down_revision = "0006_explore"

import sqlalchemy as sa

from alembic import op

_OLD_KINDS = "'image', 'video', 'link'"
_OLD_ORIGINS = "'upload', 'drop', 'paste', 'link', 'extension', 'candidate', 'seed', 'generated'"
_OLD_STATUS = "'open', 'dismissed', 'visualizing', 'visualized'"
_OLD_ACTIONS = "'extracted', 'model_suppressed', 'edited', 'confirmed', 'disabled', 'enabled'"


def _ensure_sha_index() -> None:
    op.execute("DROP INDEX IF EXISTS uq_board_items_active_sha256")
    op.execute(
        "CREATE UNIQUE INDEX uq_board_items_active_sha256 ON board_items (board_id, sha256) "
        "WHERE removed_at IS NULL AND sha256 IS NOT NULL"
    )


def _event_table(actors: str, actions: str) -> sa.Table:
    # the original checks are unnamed, so the batch rebuild copies from this definition
    t = sa.Table(
        "attribute_events",
        sa.MetaData(),
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("item_id", sa.String(), sa.ForeignKey("board_items.id"), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("before_json", sa.JSON()),
        sa.Column("after_json", sa.JSON()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint(f"action IN ({actions})"),
        sa.CheckConstraint(f"actor IN ({actors})"),
    )
    sa.Index("ix_attribute_events_item_id", t.c.item_id)
    return t


def _rebuild_items(kinds: str, origins: str) -> None:
    with op.batch_alter_table("board_items", recreate="always") as b:
        b.drop_constraint("ck_item_kind", type_="check")
        b.drop_constraint("ck_item_origin", type_="check")
        b.create_check_constraint("ck_item_kind", f"kind IN ({kinds})")
        b.create_check_constraint("ck_item_origin", f"origin IN ({origins})")


def upgrade() -> None:
    _rebuild_items(f"{_OLD_KINDS}, 'note'", f"{_OLD_ORIGINS}, 'note'")
    with op.batch_alter_table("board_items", recreate="always") as b:
        b.add_column(sa.Column("note_text", sa.String()))
        b.add_column(sa.Column("staged", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    _ensure_sha_index()
    with op.batch_alter_table("explore_options", recreate="always") as b:
        b.add_column(sa.Column("kept_item_id", sa.String()))
        b.drop_constraint("ck_option_status", type_="check")
        b.create_check_constraint("ck_option_status", f"status IN ({_OLD_STATUS}, 'kept')")
    with op.batch_alter_table(
        "attribute_events",
        recreate="always",
        copy_from=_event_table("'user', 'model', 'plugin'", f"{_OLD_ACTIONS}, 'plugin'"),
    ):
        pass
    op.create_table(
        "board_plugins",
        sa.Column("board_id", sa.String(), sa.ForeignKey("boards.id"), primary_key=True),
        sa.Column("plugin_id", sa.String(), primary_key=True),
        sa.Column("added_at", sa.String(), nullable=False),
    )
    op.create_table(
        "plugin_nodes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("board_id", sa.String(), sa.ForeignKey("boards.id"), nullable=False),
        sa.Column("plugin_id", sa.String(), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("w", sa.Float(), nullable=False),
        sa.Column("h", sa.Float(), nullable=False),
        sa.Column("input_item_ids_json", sa.JSON(), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("last_run_id", sa.String()),
        sa.Column("removed_at", sa.String()),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_plugin_nodes_board_id", "plugin_nodes", ["board_id"])
    op.create_table(
        "plugin_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("board_id", sa.String(), sa.ForeignKey("boards.id"), nullable=False),
        sa.Column("node_id", sa.String(), sa.ForeignKey("plugin_nodes.id"), nullable=False),
        sa.Column("plugin_id", sa.String(), nullable=False),
        sa.Column("input_item_ids_json", sa.JSON(), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("progress_json", sa.JSON()),
        sa.Column("output_json", sa.JSON()),
        sa.Column("error_code", sa.String()),
        sa.Column("error_message", sa.String()),
        sa.Column("claimed_at", sa.String()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String()),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')", name="ck_plugin_run_status"
        ),
    )
    op.create_index("ix_plugin_runs_board_id", "plugin_runs", ["board_id"])
    op.create_index("ix_plugin_runs_node_id", "plugin_runs", ["node_id"])


def downgrade() -> None:
    op.drop_table("plugin_runs")
    op.drop_table("plugin_nodes")
    op.drop_table("board_plugins")
    op.execute("DELETE FROM attribute_events WHERE actor = 'plugin' OR action = 'plugin'")
    with op.batch_alter_table(
        "attribute_events",
        recreate="always",
        copy_from=_event_table("'user', 'model'", _OLD_ACTIONS),
    ):
        pass
    op.execute("UPDATE explore_options SET status = 'visualized' WHERE status = 'kept'")
    with op.batch_alter_table("explore_options", recreate="always") as b:
        b.drop_column("kept_item_id")
        b.drop_constraint("ck_option_status", type_="check")
        b.create_check_constraint("ck_option_status", f"status IN ({_OLD_STATUS})")
    # notes (and their dependents) cannot exist under the old kind/origin checks
    notes = "SELECT id FROM board_items WHERE kind = 'note' OR origin = 'note'"
    for table in ("item_frames", "item_attributes", "attribute_events"):
        op.execute(f"DELETE FROM {table} WHERE item_id IN ({notes})")
    op.execute(f"UPDATE board_items SET parent_item_id = NULL WHERE parent_item_id IN ({notes})")
    op.execute("DELETE FROM board_items WHERE kind = 'note' OR origin = 'note'")
    with op.batch_alter_table("board_items", recreate="always") as b:
        b.drop_column("staged")
        b.drop_column("note_text")
    _rebuild_items(_OLD_KINDS, _OLD_ORIGINS)
    _ensure_sha_index()
