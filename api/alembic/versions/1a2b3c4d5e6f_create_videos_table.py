"""create videos table

Revision ID: 1a2b3c4d5e6f
Revises:
Create Date: 2026-04-10 17:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    videos テーブルを作成する。

    カラム:
        id         CHAR(11) PRIMARY KEY - 動画の一意識別子（Base62 64bit ID）
        title      VARCHAR NOT NULL     - 元のファイル名（表示用タイトル）
        created_at BIGINT  NOT NULL     - 登録日時（UNIX タイムスタンプ、秒単位）
    """
    op.create_table(
        "videos",
        sa.Column("id", sa.CHAR(11), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """videos テーブルを削除する。"""
    op.drop_table("videos")
