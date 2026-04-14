# 技術スタック

| 用途 | 技術 |
|------|------|
| バックエンド | FastAPI (Python 3.11) |
| 動画変換 | ffmpeg（HLS 単一ビットレート、Worker コンテナで非同期実行） |
| ジョブキュー | Redis 7（split ジョブの非同期受け渡し） |
| フロントエンド | Jinja2 テンプレート (HTML) |
| 動画再生 | hls.js |
| 動画配信 | Nginx + secure_link_md5 + proxy_cache + MinIO proxy_pass |
| 認証 | FastAPI Cookie セッション (itsdangerous) |
| データベース | PostgreSQL（動画メタ情報・ジョブ情報）|
| ORM / マイグレーション | SQLAlchemy 2.x + Alembic |
| コンテナ | Docker Compose（7コンテナ構成: db / redis / minio / createbuckets / api / worker / nginx） |
| オブジェクトストレージ | MinIO（S3 互換、HLS ファイルの永続保存） |
