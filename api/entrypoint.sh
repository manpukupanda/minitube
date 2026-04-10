#!/bin/sh
# entrypoint.sh - コンテナ起動時のエントリポイントスクリプト
#
# 1. Alembic マイグレーションを適用する（`alembic upgrade head`）
# 2. uvicorn で FastAPI アプリを起動する
#
# マイグレーションが失敗した場合はコンテナを停止させる（set -e）。
# docker-compose の depends_on + healthcheck により、
# PostgreSQL が起動済みであることが保証された後にこのスクリプトが実行される。

set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting uvicorn..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
