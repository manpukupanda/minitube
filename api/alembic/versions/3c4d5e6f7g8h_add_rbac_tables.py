"""add rbac tables

Revision ID: 3c4d5e6f7g8h
Revises: 2b3c4d5e6f7g
Create Date: 2026-04-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "3c4d5e6f7g8h"
down_revision = "2b3c4d5e6f7g"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )

    op.create_table(
        "video_permissions",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("video_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"]),
        sa.PrimaryKeyConstraint("user_id", "video_id"),
    )

    op.add_column("videos", sa.Column("owner_user_id", sa.String(), nullable=True))
    op.add_column("videos", sa.Column("description", sa.String(), nullable=True))
    op.add_column(
        "videos",
        sa.Column("visibility", sa.String(), nullable=False, server_default="public"),
    )


def downgrade() -> None:
    op.drop_column("videos", "visibility")
    op.drop_column("videos", "description")
    op.drop_column("videos", "owner_user_id")
    op.drop_table("video_permissions")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_table("users")
