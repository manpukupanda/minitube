"""add profile fields to users

Revision ID: 5e6f7g8h9i0j
Revises: 4d5e6f7g8h9i
Create Date: 2026-04-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "5e6f7g8h9i0j"
down_revision = "4d5e6f7g8h9i"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # display_name: ユーザが設定した表示名（nullable）
    op.add_column("users", sa.Column("display_name", sa.String(50), nullable=True))
    # icon_path: MinIO に保存されたアイコン画像のオブジェクトキー（nullable）
    op.add_column("users", sa.Column("icon_path", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "icon_path")
    op.drop_column("users", "display_name")
