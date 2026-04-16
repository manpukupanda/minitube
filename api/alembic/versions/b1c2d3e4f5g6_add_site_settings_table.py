"""add site_settings table

Revision ID: b1c2d3e4f5g6
Revises: a0b1c2d3e4f5
Create Date: 2026-04-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "b1c2d3e4f5g6"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("top_notice", sa.Text(), nullable=True),
        sa.Column("hero_image_url", sa.Text(), nullable=True),
        sa.Column("recommended_video_ids", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("site_settings")
