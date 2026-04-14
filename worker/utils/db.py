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


def update_video_status(conn, video_id: str, status: str) -> None:
    """
    動画の status と updated_at を更新する。

    Worker がジョブ完了・失敗時に呼び出す。

    Args:
        conn:     psycopg2 接続オブジェクト
        video_id: 動画の UUID
        status:   新しい状態（processing / ready / failed）
    """
    now = int(time.time())
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE videos SET status = %s, updated_at = %s WHERE id = %s",
            (status, now, video_id),
        )
    conn.commit()


def create_thumbnail(conn, thumbnail_id: str, video_id: str, url: str, thumb_type: str, active: bool) -> None:
    """
    thumbnails テーブルにサムネイルレコードを挿入する。

    Args:
        conn:         psycopg2 接続オブジェクト
        thumbnail_id: サムネイルの Base62 ID（11 文字）
        video_id:     動画の Base62 ID（11 文字）
        url:          MinIO 経由で参照できる URL（Nginx proxy パス）
        thumb_type:   "fixed" または "representative"
        active:       選択状態（True = active）
    """
    now = int(time.time())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO thumbnails (id, video_id, url, type, active, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (thumbnail_id, video_id, url, thumb_type, active, now),
        )
    conn.commit()
