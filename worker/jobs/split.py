"""
jobs/split.py - ffmpeg による HLS 分割処理と MinIO へのアップロード

Worker が呼び出す HLS 変換ロジック。
API のコードを import しない。
ffmpeg の stdout/stderr はそのまま Worker のログ（stdout/stderr）として出力する。

処理の流れ:
    1. /videos/{video_id}/input.mp4 を一時ディレクトリで HLS に変換する
    2. 変換成功後、全 HLS ファイル（playlist.m3u8 + segment*.ts）を MinIO にアップロード
    3. 一時ディレクトリを削除する（ローカルへの恒久保存は行わない）
    4. input.mp4 を削除する

MinIO のオブジェクトキー規約:
    hls/{video_id}/playlist.m3u8
    hls/{video_id}/segment000.ts
    hls/{video_id}/segment001.ts
    ...
"""

import glob
import logging
import os
import subprocess
import tempfile

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# input.mp4 の保存先ディレクトリ（api コンテナと共有ボリューム）
VIDEOS_DIR = "/videos"


def _get_s3_client():
    """
    MinIO への boto3 S3 クライアントを返す。

    環境変数から接続情報を取得する:
        MINIO_ENDPOINT   : MinIO の S3 API エンドポイント（例: http://minio:9000）
        MINIO_ACCESS_KEY : MinIO の root アクセスキー
        MINIO_SECRET_KEY : MinIO の root シークレットキー
    """
    endpoint = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
    access_key = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.environ.get("MINIO_SECRET_KEY", "changeme_minio_secret")

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        # MinIO はリージョンを気にしないが boto3 は必須のため設定する
        region_name="us-east-1",
    )


def _upload_hls_to_minio(video_id: str, tmp_dir: str) -> None:
    """
    一時ディレクトリ内の全 HLS ファイルを MinIO にアップロードする。

    アップロードするファイル:
        {tmp_dir}/playlist.m3u8  → hls/{video_id}/playlist.m3u8
        {tmp_dir}/segment*.ts    → hls/{video_id}/segment*.ts

    Args:
        video_id: 動画の UUID
        tmp_dir:  HLS ファイルが格納された一時ディレクトリのパス

    Raises:
        ClientError: MinIO へのアップロードに失敗した場合
        RuntimeError: playlist.m3u8 が存在しない場合
    """
    bucket = os.environ.get("MINIO_BUCKET", "minitube")
    s3 = _get_s3_client()

    playlist_local = os.path.join(tmp_dir, "playlist.m3u8")
    if not os.path.exists(playlist_local):
        raise RuntimeError(
            f"playlist.m3u8 が見つかりません（video_id={video_id}, path={playlist_local}）"
        )

    # playlist.m3u8 をアップロードする
    playlist_key = f"hls/{video_id}/playlist.m3u8"
    logger.info("MinIO アップロード開始: bucket=%s key=%s", bucket, playlist_key)
    try:
        s3.upload_file(
            playlist_local,
            bucket,
            playlist_key,
            ExtraArgs={"ContentType": "application/vnd.apple.mpegurl"},
        )
    except ClientError as e:
        raise RuntimeError(
            f"MinIO へのアップロードに失敗しました（key={playlist_key}, error={e}）"
        ) from e
    logger.info("MinIO アップロード完了: key=%s", playlist_key)

    # segment*.ts を昇順でアップロードする
    segment_files = sorted(glob.glob(os.path.join(tmp_dir, "segment*.ts")))
    if not segment_files:
        raise RuntimeError(
            f"セグメントファイルが見つかりません（video_id={video_id}, dir={tmp_dir}）"
        )

    for seg_path in segment_files:
        seg_name = os.path.basename(seg_path)
        seg_key = f"hls/{video_id}/{seg_name}"
        logger.info("MinIO アップロード開始: bucket=%s key=%s", bucket, seg_key)
        try:
            s3.upload_file(
                seg_path,
                bucket,
                seg_key,
                ExtraArgs={"ContentType": "video/mp2t"},
            )
        except ClientError as e:
            raise RuntimeError(
                f"MinIO へのアップロードに失敗しました（key={seg_key}, error={e}）"
            ) from e
        logger.info("MinIO アップロード完了: key=%s", seg_key)


def run_split(video_id: str) -> None:
    """
    /videos/{video_id}/input.mp4 を HLS 形式に変換し、MinIO に保存する。

    一時ディレクトリで HLS を生成し、MinIO アップロード後に削除する。
    ローカルへの恒久保存は行わない。

    ffmpeg オプション:
        -i input_path         : 入力ファイルの指定
        -c:v libx264          : 映像を H.264 でエンコード（HLS との互換性を確保）
        -c:a aac              : 音声を AAC でエンコード（HLS との互換性を確保）
        -start_number 0       : セグメント番号を 0 から開始する
        -hls_time 4           : 各セグメントの長さを 4 秒にする
        -hls_list_size 0      : プレイリストにすべてのセグメントを記録する（VOD 用）
        -hls_segment_filename : セグメントファイルの命名パターン
        -f hls                : 出力フォーマットを HLS に指定

    MinIO のオブジェクトキー規約:
        hls/{video_id}/playlist.m3u8
        hls/{video_id}/segment000.ts
        hls/{video_id}/segment001.ts
        ...

    Args:
        video_id: 動画の UUID

    Raises:
        RuntimeError: input.mp4 が存在しない場合、ffmpeg が失敗した場合、
                      または MinIO へのアップロードに失敗した場合
    """
    input_path = os.path.join(VIDEOS_DIR, video_id, "input.mp4")

    if not os.path.exists(input_path):
        raise RuntimeError(
            f"input.mp4 が見つかりません（video_id={video_id}, path={input_path}）"
        )

    # 一時ディレクトリに HLS を出力する（コンテキストマネージャで自動削除）
    with tempfile.TemporaryDirectory() as tmp_dir:
        playlist_path = os.path.join(tmp_dir, "playlist.m3u8")
        segment_pattern = os.path.join(tmp_dir, "segment%03d.ts")

        # ffmpeg コマンドを組み立てる
        command = [
            "ffmpeg",
            "-i", input_path,
            # 映像: H.264 エンコード（HLS/ブラウザとの互換性確保）
            "-c:v", "libx264",
            # 音声: AAC エンコード（ブラウザでの再生互換性確保）
            "-c:a", "aac",
            # セグメント番号を 0 から開始
            "-start_number", "0",
            # セグメント長を 4 秒に設定
            "-hls_time", "4",
            # VOD（録画配信）のため、すべてのセグメントをプレイリストに記録
            "-hls_list_size", "0",
            # セグメントファイルの命名パターン（例: segment000.ts）
            "-hls_segment_filename", segment_pattern,
            # 出力フォーマットを HLS に指定
            "-f", "hls",
            playlist_path,
        ]

        # ffmpeg を実行する
        # stdout/stderr はそのまま Worker のログとして出力する
        result = subprocess.run(command)

        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg による HLS 変換に失敗しました（video_id={video_id}, "
                f"returncode={result.returncode}）"
            )

        # MinIO に HLS ファイルをアップロードする
        # アップロード失敗時は RuntimeError を送出してジョブを error にする
        _upload_hls_to_minio(video_id, tmp_dir)

    # 一時ディレクトリは with ブロック終了時に自動削除される

    # 変換成功後、入力ファイルを削除する
    if os.path.exists(input_path):
        os.remove(input_path)

    # 入力ファイルのディレクトリが空になった場合は削除する
    output_dir = os.path.join(VIDEOS_DIR, video_id)
    try:
        os.rmdir(output_dir)
    except OSError:
        # 空でない場合（他のファイルが残っている場合）は無視する
        pass
