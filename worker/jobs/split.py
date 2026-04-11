"""
jobs/split.py - ffmpeg による HLS 分割処理

Worker が呼び出す HLS 変換ロジック。
API のコードを import しない。
ffmpeg の stdout/stderr はそのまま Worker のログ（stdout/stderr）として出力する。
"""

import os
import subprocess

# HLS ファイルの出力先ディレクトリ（api コンテナと同じボリュームをマウント）
VIDEOS_DIR = "/videos"


def run_split(video_id: str) -> None:
    """
    /videos/{video_id}/input.mp4 を HLS 形式に変換する。

    出力ファイル:
        /videos/{video_id}/playlist.m3u8  - HLS プレイリスト
        /videos/{video_id}/segment000.ts  - セグメントファイル（4 秒ごと）
        /videos/{video_id}/segment001.ts
        ...

    変換成功後、input.mp4 を削除する。

    ffmpeg オプション:
        -i input_path         : 入力ファイルの指定
        -c:v libx264          : 映像を H.264 でエンコード（HLS との互換性を確保）
        -c:a aac              : 音声を AAC でエンコード（HLS との互換性を確保）
        -start_number 0       : セグメント番号を 0 から開始する
        -hls_time 4           : 各セグメントの長さを 4 秒にする
        -hls_list_size 0      : プレイリストにすべてのセグメントを記録する（VOD 用）
        -hls_segment_filename : セグメントファイルの命名パターン
        -f hls                : 出力フォーマットを HLS に指定

    Args:
        video_id: 動画の UUID

    Raises:
        RuntimeError: input.mp4 が存在しない場合、または ffmpeg が失敗した場合
    """
    output_dir = os.path.join(VIDEOS_DIR, video_id)
    input_path = os.path.join(output_dir, "input.mp4")
    playlist_path = os.path.join(output_dir, "playlist.m3u8")
    segment_pattern = os.path.join(output_dir, "segment%03d.ts")

    if not os.path.exists(input_path):
        raise RuntimeError(
            f"input.mp4 が見つかりません（video_id={video_id}, path={input_path}）"
        )

    # ffmpeg コマンドを組み立てる（API の convert_to_hls と同じオプション）
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
    # stdout/stderr はそのまま Worker のログとして出力する（コンテナ内にファイルを書かない）
    result = subprocess.run(command)

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg による HLS 変換に失敗しました（video_id={video_id}, "
            f"returncode={result.returncode}）"
        )

    # 変換成功後、入力ファイルを削除する
    if os.path.exists(input_path):
        os.remove(input_path)
