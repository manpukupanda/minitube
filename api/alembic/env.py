"""
alembic/env.py - Alembic マイグレーション実行環境

このファイルは `alembic upgrade head` などのコマンド実行時に読み込まれる。
DATABASE_URL 環境変数から接続情報を取得し、main.py の Base.metadata を
ターゲットメタデータとして使用することで、モデル定義とスキーマを同期させる。
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# alembic/ の親ディレクトリ（api/）をパスに追加し、main.py をインポートできるようにする
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import Base  # noqa: E402

# alembic.ini の [alembic] セクションの設定オブジェクト
config = context.config

# alembic.ini のロギング設定を適用する
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# マイグレーション対象のメタデータ（autogenerate で使用する）
target_metadata = Base.metadata


def get_url() -> str:
    """
    DATABASE_URL 環境変数からデータベース接続文字列を取得する。
    環境変数が未設定の場合はデフォルト値（開発用）を使用する。
    """
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://minitube:changeme_replace_in_production@db/minitube",
    )


def run_migrations_offline() -> None:
    """
    オフラインモード（--sql オプション）でマイグレーションを実行する。

    データベースへの実接続なしに SQL スクリプトを生成する。
    CI/CD パイプラインで SQL を事前確認する際などに使用する。
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    オンラインモード（通常実行）でマイグレーションを実行する。

    実際のデータベース接続を確立し、マイグレーションを適用する。
    コンテナ起動時の `alembic upgrade head` はこのモードで動作する。
    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
