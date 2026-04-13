"""create jobs table

Revision ID: 2b3c4d5e6f7g
Revises: 1a2b3c4d5e6f
Create Date: 2026-04-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2b3c4d5e6f7g"
down_revision: Union[str, None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    jobs テーブルを作成する。

    カラム:
        id            CHAR(11) PRIMARY KEY - ジョブの一意識別子（Base62 64bit ID）
        video_id      CHAR(11) NOT NULL    - 対象動画の ID
        type          VARCHAR  NOT NULL    - ジョブ種別（'split' のみ）
        status        VARCHAR  NOT NULL    - ジョブ状態（queued/processing/completed/error）
        error_message VARCHAR  NULL        - エラー時のメッセージ
        created_at    BIGINT   NOT NULL    - 作成日時（UNIX タイムスタンプ、秒単位）
        updated_at    BIGINT   NOT NULL    - 更新日時（UNIX タイムスタンプ、秒単位）

    制約:
        UNIQUE(video_id, type) - 同一動画・同一種別のジョブは1つのみ
    """
    op.create_table(
        "jobs",
        sa.Column("id", sa.CHAR(11), nullable=False),
        sa.Column("video_id", sa.CHAR(11), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_id", "type", name="uq_jobs_video_id_type"),
    )


def downgrade() -> None:
    """jobs テーブルを削除する。"""
    op.drop_table("jobs")
