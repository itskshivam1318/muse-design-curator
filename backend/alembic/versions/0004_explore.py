"""explore: explorations, options, generated board items"""

revision = "0004_explore"
down_revision = "0003"

import sqlalchemy as sa

from alembic import op

_OLD_ORIGINS = "'upload', 'drop', 'paste', 'link', 'extension', 'candidate', 'seed'"
_OLD_RIGHTS = "'user_supplied', 'licensed'"


def _ensure_sha_index() -> None:
    # batch recreate may not carry the partial unique index across
    op.execute("DROP INDEX IF EXISTS uq_board_items_active_sha256")
    op.execute(
        "CREATE UNIQUE INDEX uq_board_items_active_sha256 ON board_items (board_id, sha256) "
        "WHERE removed_at IS NULL AND sha256 IS NOT NULL"
    )


def upgrade() -> None:
    op.create_table(
        "explorations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("board_id", sa.String(), sa.ForeignKey("boards.id"), nullable=False),
        sa.Column("item_id", sa.String(), sa.ForeignKey("board_items.id"), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("item_id", "key"),
    )
    op.create_index("ix_explorations_board_id", "explorations", ["board_id"])
    op.create_table(
        "explore_options",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("exploration_id", sa.String(), sa.ForeignKey("explorations.id"), nullable=False),
        sa.Column("parent_option_id", sa.String(), sa.ForeignKey("explore_options.id")),
        sa.Column("batch", sa.Integer(), nullable=False),
        sa.Column("steer", sa.String()),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("distance", sa.String(), nullable=False),
        sa.Column("value_json", sa.JSON()),
        sa.Column("keeps_json", sa.JSON()),
        sa.Column("edit_prompt", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("last_error", sa.String()),
        sa.Column("x", sa.Float()),
        sa.Column("y", sa.Float()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "status IN ('open', 'dismissed', 'visualizing', 'visualized')",
            name="ck_option_status",
        ),
    )
    op.create_index("ix_explore_options_exploration_id", "explore_options", ["exploration_id"])
    with op.batch_alter_table("board_items", recreate="always") as b:
        b.add_column(
            sa.Column(
                "explore_option_id",
                sa.String(),
                sa.ForeignKey("explore_options.id", name="fk_item_explore_option"),
            )
        )
        b.add_column(sa.Column("generation_json", sa.JSON()))
        b.add_column(sa.Column("check_json", sa.JSON()))
        b.drop_constraint("ck_item_origin", type_="check")
        b.drop_constraint("ck_item_rights", type_="check")
        b.create_check_constraint("ck_item_origin", f"origin IN ({_OLD_ORIGINS}, 'generated')")
        b.create_check_constraint(
            "ck_item_rights", f"rights_status IN ({_OLD_RIGHTS}, 'generated')"
        )
    _ensure_sha_index()


def downgrade() -> None:
    op.execute("DELETE FROM board_items WHERE origin = 'generated'")
    with op.batch_alter_table("board_items", recreate="always") as b:
        b.drop_column("check_json")
        b.drop_column("generation_json")
        b.drop_column("explore_option_id")
        b.drop_constraint("ck_item_origin", type_="check")
        b.drop_constraint("ck_item_rights", type_="check")
        b.create_check_constraint("ck_item_origin", f"origin IN ({_OLD_ORIGINS})")
        b.create_check_constraint("ck_item_rights", f"rights_status IN ({_OLD_RIGHTS})")
    _ensure_sha_index()
    op.drop_table("explore_options")
    op.drop_table("explorations")
