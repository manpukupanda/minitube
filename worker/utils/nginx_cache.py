"""
utils/nginx_cache.py - Nginx proxy_cache ファイル削除ユーティリティ

Nginx の proxy_cache は、キャッシュキーを MD5 化したハッシュ値を
ファイル名として `levels=1:2` ディレクトリ階層に保存する。

キャッシュキーの設定（nginx.conf）:
    proxy_cache_key "$uri";

パス構築ルール（levels=1:2 の場合）:
    {cache_dir}/{md5[-1]}/{md5[-3:-1]}/{md5}

例:
    uri  = /videos/abc123/segment000.ts
    md5  = hashlib.md5(uri.encode()).hexdigest()
         = "1a3f9c8d7b2e4f6a0c5d8e1f3a7b9c2d"
    path = /tmp/nginx/hls_cache/d/2c/1a3f9c8d7b2e4f6a0c5d8e1f3a7b9c2d
"""

import hashlib
import logging
import os

logger = logging.getLogger(__name__)

# Nginx キャッシュディレクトリ（nginx コンテナと共有ボリューム経由でアクセス）
NGINX_CACHE_DIR = os.environ.get("NGINX_CACHE_DIR", "/tmp/nginx/hls_cache")


def get_nginx_cache_path(uri: str, cache_dir: str = NGINX_CACHE_DIR) -> str:
    """
    URI に対応する Nginx キャッシュファイルのパスを返す。

    Nginx の proxy_cache_key "$uri" と levels=1:2 に従ってパスを構築する。

    Args:
        uri:       キャッシュキーとなる URI パス（例: /videos/{id}/segment000.ts）
        cache_dir: Nginx のキャッシュディレクトリ

    Returns:
        キャッシュファイルの絶対パス
    """
    md5 = hashlib.md5(uri.encode()).hexdigest()
    return os.path.join(cache_dir, md5[-1], md5[-3:-1], md5)


def delete_nginx_cache_file(uri: str, cache_dir: str = NGINX_CACHE_DIR) -> bool:
    """
    指定した URI のキャッシュファイルを削除する。

    Args:
        uri:       削除対象の URI パス
        cache_dir: Nginx のキャッシュディレクトリ

    Returns:
        ファイルを削除した場合は True、存在しなかった場合は False
    """
    path = get_nginx_cache_path(uri, cache_dir)
    if os.path.exists(path):
        try:
            os.remove(path)
            logger.info("Nginx キャッシュ削除: uri=%s path=%s", uri, path)
            return True
        except OSError as e:
            logger.warning("Nginx キャッシュ削除失敗: uri=%s path=%s error=%s", uri, path, e)
    return False


def delete_nginx_cache_for_video(
    video_id: str,
    segment_names: list,
    cache_dir: str = NGINX_CACHE_DIR,
) -> int:
    """
    指定した動画の HLS キャッシュファイル（playlist.m3u8 + 各セグメント）を削除する。

    Args:
        video_id:      動画の UUID
        segment_names: セグメントファイル名のリスト（例: ["segment000.ts", "segment001.ts"]）
        cache_dir:     Nginx のキャッシュディレクトリ

    Returns:
        削除したキャッシュファイルの数
    """
    deleted = 0

    # playlist.m3u8 のキャッシュを削除する
    if delete_nginx_cache_file(f"/videos/{video_id}/playlist.m3u8", cache_dir):
        deleted += 1

    # 各セグメントのキャッシュを削除する
    for name in segment_names:
        if delete_nginx_cache_file(f"/videos/{video_id}/{name}", cache_dir):
            deleted += 1

    logger.info(
        "Nginx キャッシュ削除完了: video_id=%s, 削除数=%d", video_id, deleted
    )
    return deleted
