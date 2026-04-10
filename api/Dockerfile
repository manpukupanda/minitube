# ==============================================================
# FastAPI コンテナ用 Dockerfile
#
# ベースイメージ: python:3.11-slim
#   - 軽量な Debian ベースのイメージを使用する
#
# インストール内容:
#   - ffmpeg: mp4 → HLS 変換に使用
#   - pip パッケージ: requirements.txt に記載のとおり
#
# 起動コマンド:
#   - entrypoint.sh が Alembic マイグレーションを適用してから
#     uvicorn を起動する
# ==============================================================

FROM python:3.11-slim

# ビルド時のログを即時出力するために標準出力バッファを無効化する
ENV PYTHONUNBUFFERED=1

# システムパッケージのアップデートと ffmpeg のインストール
# ffmpeg は mp4 → HLS（playlist.m3u8 + segment*.ts）変換に必要
# インストール後にキャッシュを削除してイメージサイズを削減する
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg dos2unix \
    && rm -rf /var/lib/apt/lists/*

# アプリケーションの作業ディレクトリを設定
WORKDIR /app

# 依存パッケージを先にコピー・インストールする
# （ソースコードより先にインストールすることで Docker キャッシュを活用できる）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションのソースコードをコピー
COPY . .

# HLS 出力先ディレクトリを作成しておく
# （ボリュームマウント前に存在しないとパーミッションエラーになる場合がある）
RUN mkdir -p /videos

# エントリポイントスクリプトをコピーして実行権限を付与する
# dos2unix で CRLF → LF に変換する（Windows 環境でクローンした場合の対策）
COPY entrypoint.sh /entrypoint.sh
RUN dos2unix /entrypoint.sh && chmod +x /entrypoint.sh

# entrypoint.sh でマイグレーション適用後に uvicorn を起動する
CMD ["/entrypoint.sh"]
