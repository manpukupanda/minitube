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
#   - uvicorn を使って FastAPI アプリを 0.0.0.0:8000 で起動する
# ==============================================================

FROM python:3.11-slim

# ビルド時のログを即時出力するために標準出力バッファを無効化する
ENV PYTHONUNBUFFERED=1

# システムパッケージのアップデートと ffmpeg のインストール
# ffmpeg は mp4 → HLS（playlist.m3u8 + segment*.ts）変換に必要
# インストール後にキャッシュを削除してイメージサイズを削減する
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
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

# uvicorn で FastAPI アプリを起動する
# --host 0.0.0.0 : コンテナ外からアクセス可能にする
# --port 8000    : 内部ポート（docker-compose でマッピングする）
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
