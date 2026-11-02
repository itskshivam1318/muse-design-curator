"""item analysis: parts, dimension types, content types, board dimensions"""

revision = "0008_item_analysis"
down_revision = "0007_round2"

import sqlalchemy as sa

from alembic import op


def upgrade() -> None:
    with op.batch_alter_table("boards", recreate="always") as b:
        b.add_column(sa.Column("learned_json", sa.JSON()))
        b.add_column(sa.Column("dimensions_json", sa.JSON()))
        b.add_column(sa.Column("declined_json", sa.JSON()))
    with op.batch_alter_table("board_items", recreate="always") as b:
        b.add_column(sa.Column("content_type", sa.String()))
        b.add_column(sa.Column("extracted_part", sa.String()))
        b.create_check_constraint(
            "ck_item_content_type",
            "content_type IS NULL OR content_type IN ('image', 'ui', 'text')",
        )
    with op.batch_alter_table("item_attributes", recreate="always") as b:
        b.add_column(sa.Column("dim_type", sa.String(), nullable=False, server_default="abstract"))
        b.add_column(sa.Column("prompt", sa.String()))
        b.add_column(sa.Column("spec_json", sa.JSON()))
        b.add_column(
            sa.Column("removed", sa.Boolean(), nullable=False, server_default=sa.text("0"))
        )
        b.create_check_constraint("ck_attribute_dim_type", "dim_type IN ('physical', 'abstract')")
    op.create_table(
        "item_parts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("item_id", sa.String(), sa.ForeignKey("board_items.id"), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("region_kind", sa.String(), nullable=False),
        sa.Column("region_json", sa.JSON()),
        sa.Column("mask_path", sa.String()),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("removed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("item_id", "key"),
        sa.CheckConstraint(
            "region_kind IN ('mask', 'box', 'text_range')", name="ck_part_region_kind"
        ),
        sa.CheckConstraint("source IN ('ai', 'you')", name="ck_part_source"),
    )
    op.create_index("ix_item_parts_item_id", "item_parts", ["item_id"])
    # backfill
    op.execute("UPDATE item_attributes SET dim_type = 'physical' WHERE part IS NOT NULL")
    op.execute("UPDATE board_items SET content_type = 'text' WHERE kind = 'note'")
    op.execute("UPDATE board_items SET content_type = 'image' WHERE kind IN ('image', 'video')")
    conn = op.get_bind()
    from app.db.ids import PREFIXES, new_id, now_iso

    rows = conn.execute(
        sa.text(
            "SELECT DISTINCT item_id, part FROM item_attributes "
            "WHERE part IS NOT NULL ORDER BY item_id, part"
        )
    ).fetchall()
    for item_id, part in rows:
        conn.execute(
            sa.text(
                "INSERT INTO item_parts (id, item_id, key, label, region_kind, source, removed, "
                "created_at) VALUES (:id, :item_id, :key, :label, 'mask', 'ai', 0, :ts)"
            ),
            {
                "id": new_id(PREFIXES["part"]), "item_id": item_id, "key": part,
                "label": part.replace("_", " ").capitalize(), "ts": now_iso(),
            },
        )  # fmt: skip


def downgrade() -> None:
    op.drop_index("ix_item_parts_item_id", table_name="item_parts")
    op.drop_table("item_parts")
    with op.batch_alter_table("item_attributes", recreate="always") as b:
        b.drop_constraint("ck_attribute_dim_type", type_="check")
        b.drop_column("removed")
        b.drop_column("spec_json")
        b.drop_column("prompt")
        b.drop_column("dim_type")
    with op.batch_alter_table("board_items", recreate="always") as b:
        b.drop_constraint("ck_item_content_type", type_="check")
        b.drop_column("extracted_part")
        b.drop_column("content_type")
    with op.batch_alter_table("boards", recreate="always") as b:
        b.drop_column("declined_json")
        b.drop_column("dimensions_json")
        b.drop_column("learned_json")
