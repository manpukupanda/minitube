"""create favorites table

Revision ID: 8h9i0j1k2l3m
Revises: 7g8h9i0j1k2l
Create Date: 2026-04-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "8h9i0j1k2l3m"
down_revision = "7g8h9i0j1k2l"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "favorites",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "video_id",
            sa.String(),
            sa.ForeignKey("videos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "video_id"),
    )
    op.create_index("ix_favorites_user_id", "favorites", ["user_id"])
    op.create_index("ix_favorites_created_at", "favorites", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_favorites_created_at", table_name="favorites")
    op.drop_index("ix_favorites_user_id", table_name="favorites")
    op.drop_table("favorites")
