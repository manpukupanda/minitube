"""add categories and video meta

Revision ID: 4d5e6f7g8h9i
Revises: 3c4d5e6f7g8h
Create Date: 2026-04-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "4d5e6f7g8h9i"
down_revision = "3c4d5e6f7g8h"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # categories テーブルを作成する
    op.create_table(
        "categories",
        sa.Column("id", sa.CHAR(11), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # videos テーブルにカテゴリ・ステータス・更新日時カラムを追加する
    op.add_column("videos", sa.Column("category_id", sa.CHAR(11), nullable=True))
    op.create_foreign_key(
        "fk_videos_category_id",
        "videos",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "videos",
        sa.Column("status", sa.String(), nullable=False, server_default="ready"),
    )
    op.add_column("videos", sa.Column("updated_at", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("videos", "updated_at")
    op.drop_column("videos", "status")
    op.drop_constraint("fk_videos_category_id", "videos", type_="foreignkey")
    op.drop_column("videos", "category_id")
    op.drop_table("categories")
