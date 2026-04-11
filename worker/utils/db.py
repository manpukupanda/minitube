"""
utils/db.py - Worker 用データベース接続ヘルパー

PostgreSQL への接続とジョブ状態更新の責務を担う。
Worker は jobs.status を 'processing' / 'completed' / 'error' に UPDATE する。
Worker は jobs レコードを INSERT しない（API の責務）。
"""

import os
import time

import psycopg2

# DATABASE_URL は環境変数から取得する
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://minitube:changeme_replace_in_production@db/minitube",
)


def get_connection():
    """PostgreSQL 接続を返す。"""
    return psycopg2.connect(DATABASE_URL)


def get_job(conn, job_id: str) -> dict | None:
    """
    指定した job_id のジョブ情報を取得する。

    Args:
        conn:   psycopg2 接続オブジェクト
        job_id: ジョブの UUID

    Returns:
        dict: ジョブ情報（id, video_id, type, status, error_message）
              見つからない場合は None
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, video_id, type, status, error_message FROM jobs WHERE id = %s",
            (job_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "video_id": row[1],
        "type": row[2],
        "status": row[3],
        "error_message": row[4],
    }


def update_job_status(conn, job_id: str, status: str, error_message: str | None = None) -> None:
    """
    ジョブの状態を更新する。

    Worker のみがこの関数を呼び出す。API は jobs.status を UPDATE しない。

    Args:
        conn:          psycopg2 接続オブジェクト
        job_id:        ジョブの UUID
        status:        新しい状態（processing / completed / error）
        error_message: エラーメッセージ（error 時のみ設定）
    """
    now = int(time.time())
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET status = %s, error_message = %s, updated_at = %s WHERE id = %s",
            (status, error_message, now, job_id),
        )
    conn.commit()
