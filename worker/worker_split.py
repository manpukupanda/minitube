"""
worker_split.py - split ジョブ処理 Worker のエントリポイント

Redis Queue から job_id を受け取り、HLS 分割処理を実行する。

処理の流れ:
    1. Redis Queue（split_jobs）を BLPOP で常時監視する
    2. job_id を受け取り、DB から video_id を取得する
    3. jobs.status を 'processing' に更新する
    4. jobs/split.py の run_split() で ffmpeg を実行する
    5. 成功時: jobs.status を 'completed' に更新する
    6. 失敗時: jobs.status を 'error' に、error_message を保存する

禁止事項:
    - 次のジョブを enqueue してはならない
    - jobs レコードを INSERT してはならない
    - コンテナ内にログファイルを書き込んではならない
"""

import logging
import os
import sys

import redis

from jobs.split import run_split
from utils.db import get_connection, get_job, update_job_status, update_video_status

# ログ設定: すべて stdout/stderr に出力する（コンテナ内にファイルを書かない）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Redis キュー名
SPLIT_QUEUE = "split_jobs"

# REDIS_URL は環境変数から取得する
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


def main() -> None:
    """
    Redis Queue を常時監視して split ジョブを処理するメインループ。

    BLPOP を使ってキューを監視し、job_id を受け取ったら処理を実行する。
    エラーが発生しても次のジョブの処理を継続する。
    """
    logger.info("Worker 起動: Redis Queue '%s' を監視します（%s）", SPLIT_QUEUE, REDIS_URL)

    redis_client = redis.from_url(REDIS_URL)

    while True:
        try:
            # BLPOP: キューが空の場合はブロックして待機する（タイムアウトなし）
            result = redis_client.blpop(SPLIT_QUEUE, timeout=0)
            if result is None:
                continue

            _, job_id_bytes = result
            job_id = job_id_bytes.decode("utf-8")
            logger.info("ジョブ受信: job_id=%s", job_id)

        except Exception as e:
            logger.error("Redis からのジョブ受信に失敗しました: %s", e)
            continue

        # DB 接続を確立して処理を実行する
        conn = None
        try:
            conn = get_connection()

            # DB からジョブ情報を取得する
            job = get_job(conn, job_id)
            if job is None:
                logger.error("ジョブが見つかりません: job_id=%s", job_id)
                continue

            video_id = job["video_id"]
            logger.info("処理開始: job_id=%s, video_id=%s", job_id, video_id)

            # jobs.status を 'processing' に更新する
            update_job_status(conn, job_id, "processing")
            update_video_status(conn, video_id, "processing")

            # ffmpeg による HLS 分割処理を実行する
            run_split(video_id)

            # 成功時: jobs.status を 'completed' に更新する
            update_job_status(conn, job_id, "completed")
            update_video_status(conn, video_id, "ready")
            logger.info("処理完了: job_id=%s, video_id=%s", job_id, video_id)

        except Exception as e:
            # 失敗時: jobs.status を 'error' に更新し、エラーメッセージを保存する
            error_message = str(e)[:500]  # DB カラムのサイズに合わせて切り詰める
            logger.error("処理失敗: job_id=%s, error=%s", job_id, error_message)
            if conn is not None:
                try:
                    update_job_status(conn, job_id, "error", error_message)
                    update_video_status(conn, video_id, "failed")
                except Exception as db_err:
                    logger.error("エラー状態の保存に失敗しました: %s", db_err)

        finally:
            if conn is not None:
                conn.close()


if __name__ == "__main__":
    main()
