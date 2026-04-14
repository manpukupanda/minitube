# 本番デプロイ

## セキュリティ上の必須事項

本番環境では以下を必ず設定・変更すること。

### 1. 強固なシークレットキーの生成

```bash
# ランダムな 32 バイトの SECRET_KEY を生成する
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 2. 環境変数の設定

```bash
export SECRET_KEY="上記で生成した値"
export INITIAL_ADMIN_PASSWORD="強固なパスワード"
export POSTGRES_PASSWORD="強固なパスワード"
export POSTGRES_USER="minitube"
export POSTGRES_DB="minitube"
export MINIO_ACCESS_KEY="強固なアクセスキー"
export MINIO_SECRET_KEY="強固なシークレットキー"
export MINIO_BUCKET="minitube"
```

または `.env` ファイルに記載する（Git にコミットしないこと）。

### 3. HTTPS の設定（本番では必須）

本番環境では Cookie の `Secure` フラグを有効にすること。`main.py` の SessionMiddleware 設定を変更する:

```python
# 本番環境では https_only=True に変更する
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY"),
    same_site="lax",
    https_only=True,  # 本番では True にする
)
```

Nginx に SSL/TLS 設定を追加し、Let's Encrypt などで証明書を取得する。

### 4. Nginx のアクセス制御（オプション）

必要に応じて IP アドレス制限を追加する:

```nginx
location /videos/ {
    # IP アドレス制限の例
    allow 192.168.1.0/24;
    deny all;
    # ... secure_link 設定 ...
}
```

### 5. ディスク容量の監視

動画ファイルは `/volumes/videos_data` に蓄積されるため、定期的な監視・削除が必要。

## デプロイコマンド例

```bash
# 本番サーバで実行
git pull origin main

# 環境変数を設定
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
export INITIAL_ADMIN_PASSWORD="your_admin_password"
export POSTGRES_PASSWORD="your_strong_db_password"
export POSTGRES_USER="minitube"
export POSTGRES_DB="minitube"
export MINIO_ACCESS_KEY="your_minio_access_key"
export MINIO_SECRET_KEY="your_minio_secret_key"
export MINIO_BUCKET="minitube"

# ビルドと起動
docker compose up --build -d

# ログ確認
docker compose logs -f
```
