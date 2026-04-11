# ==============================================================
# Worker コンテナ用 Dockerfile
#
# ベースイメージ: python:3.11-slim
#   - 軽量な Debian ベースのイメージを使用する
#
# インストール内容:
#   - ffmpeg: mp4 → HLS 変換に使用（API コンテナには不要）
#   - pip パッケージ: requirements.txt に記載のとおり
#
# 起動コマンド:
#   - worker_split.py が Redis Queue を監視して split ジョブを処理する
# ==============================================================

FROM python:3.11-slim

# ビルド時のログを即時出力するために標準出力バッファを無効化する
ENV PYTHONUNBUFFERED=1

# システムパッケージのアップデートと ffmpeg のインストール
# ffmpeg は mp4 → HLS（playlist.m3u8 + segment*.ts）変換に必要
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# アプリケーションの作業ディレクトリを設定
WORKDIR /app

# 依存パッケージを先にコピー・インストールする
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションのソースコードをコピー
COPY . .

# HLS 出力先ディレクトリを作成しておく
RUN mkdir -p /videos

# Worker エントリポイントを起動する
CMD ["python", "worker_split.py"]
