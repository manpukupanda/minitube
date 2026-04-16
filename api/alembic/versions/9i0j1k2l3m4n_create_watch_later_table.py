"""create watch_later table

Revision ID: 9i0j1k2l3m4n
Revises: 8h9i0j1k2l3m
Create Date: 2026-04-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "9i0j1k2l3m4n"
down_revision = "8h9i0j1k2l3m"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watch_later",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "video_id",
            sa.String(),
            sa.ForeignKey("videos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("auto_removed_at", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "video_id"),
    )
    op.create_index("ix_watch_later_user_id", "watch_later", ["user_id"])
    op.create_index("ix_watch_later_created_at", "watch_later", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_watch_later_created_at", table_name="watch_later")
    op.drop_index("ix_watch_later_user_id", table_name="watch_later")
    op.drop_table("watch_later")
