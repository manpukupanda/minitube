"""create thumbnails table

Revision ID: 6f7g8h9i0j1k
Revises: 5e6f7g8h9i0j
Create Date: 2026-04-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "6f7g8h9i0j1k"
down_revision = "5e6f7g8h9i0j"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "thumbnails",
        sa.Column("id", sa.CHAR(11), nullable=False),
        sa.Column("video_id", sa.CHAR(11), sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_thumbnails_video_id", "thumbnails", ["video_id"])


def downgrade() -> None:
    op.drop_index("ix_thumbnails_video_id", table_name="thumbnails")
    op.drop_table("thumbnails")
