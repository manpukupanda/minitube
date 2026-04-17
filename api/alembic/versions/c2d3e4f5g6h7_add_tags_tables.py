"""add tags tables

Revision ID: c2d3e4f5g6h7
Revises: b1c2d3e4f5g6
Create Date: 2026-04-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "c2d3e4f5g6h7"
down_revision = "b1c2d3e4f5g6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.CHAR(11), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_tags_name", "tags", ["name"], unique=False)
    op.create_index("ix_tags_slug", "tags", ["slug"], unique=False)

    op.create_table(
        "video_tags",
        sa.Column("video_id", sa.CHAR(11), nullable=False),
        sa.Column("tag_id", sa.CHAR(11), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("video_id", "tag_id"),
    )
    op.create_index("ix_video_tags_video_id", "video_tags", ["video_id"], unique=False)
    op.create_index("ix_video_tags_tag_id", "video_tags", ["tag_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_video_tags_tag_id", table_name="video_tags")
    op.drop_index("ix_video_tags_video_id", table_name="video_tags")
    op.drop_table("video_tags")

    op.drop_index("ix_tags_slug", table_name="tags")
    op.drop_index("ix_tags_name", table_name="tags")
    op.drop_table("tags")
