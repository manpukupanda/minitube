"""create watch_history table

Revision ID: 7g8h9i0j1k2l
Revises: 6f7g8h9i0j1k
Create Date: 2026-04-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "7g8h9i0j1k2l"
down_revision = "6f7g8h9i0j1k"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watch_history",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "video_id",
            sa.String(),
            sa.ForeignKey("videos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("last_watched_at", sa.BigInteger(), nullable=False),
        sa.Column("last_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("user_id", "video_id"),
    )
    op.create_index("ix_watch_history_user_id", "watch_history", ["user_id"])
    op.create_index(
        "ix_watch_history_last_watched_at",
        "watch_history",
        ["last_watched_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_watch_history_last_watched_at", table_name="watch_history")
    op.drop_index("ix_watch_history_user_id", table_name="watch_history")
    op.drop_table("watch_history")
