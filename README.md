# minitube

最小構成の動画配信 Web アプリ。mp4 をアップロードすると HLS に変換し、認証済みユーザだけがブラウザで再生できる。

---

## 概要

このアプリは「製品化」ではなく、動画配信の仕組みを理解するための最小構成を目的とする。

- **認証**: FastAPI の Cookie セッション（パスワード認証）
- **変換**: ffmpeg により mp4 → HLS（playlist.m3u8 + segment*.ts）
- **配信**: Nginx による HLS 直接配信 + secure_link_md5 署名検証
- **保護**: 署名付きURL（1 時間有効）で認証済みユーザのみが視聴可能

---

## コンテナ構成図

```
ブラウザ
   │
   │ HTTP (ポート 80)
   ▼
┌─────────────────────────────┐
│         Nginx コンテナ        │
│                               │
│  /api/*   → FastAPI へ proxy │
│  /videos/ → HLS 直接配信     │
│             (secure_link_md5) │
└─────────────┬───────────────┘
              │
              │ proxy_pass http://api:8000
              ▼
┌─────────────────────────────┐
│       FastAPI コンテナ        │
│                               │
│  /login    ログインページ     │
│  /upload   アップロード       │
│  /player/  プレイヤーページ  │
│  /api/...  認証・変換・署名  │
│                               │
│  ffmpeg: mp4 → HLS 変換      │
│  SQLAlchemy: DB アクセス      │
└──────┬──────────┬────────────┘
       │          │
       │ Volume   │ PostgreSQL
       ▼          ▼
┌──────────┐  ┌─────────────────────────────┐
│  /videos  │  │    PostgreSQL コンテナ（db）  │
│ (共有Vol) │  │                               │
│           │  │  videos テーブル              │
│ playlist  │  │  id, title, created_at        │
│ *.ts ...  │  │                               │
└──────────┘  └─────────────────────────────┘
```

---

## 認証フロー図

```
ユーザ          ブラウザ         Nginx           FastAPI
  │               │               │               │
  │ アクセス       │               │               │
  │──────────────▶│               │               │
  │               │ GET /upload   │               │
  │               │──────────────▶│               │
  │               │               │ proxy /upload │
  │               │               │──────────────▶│
  │               │               │               │ Cookie なし
  │               │               │               │ → 303 /login
  │               │◀──────────────────────────────│
  │               │               │               │
  │ パスワード入力 │               │               │
  │──────────────▶│               │               │
  │               │ POST /api/login               │
  │               │──────────────▶│               │
  │               │               │ proxy /api/   │
  │               │               │──────────────▶│
  │               │               │               │ パスワード照合
  │               │               │               │ Cookie 発行
  │               │◀──────────────────────────────│
  │               │ Set-Cookie: session=...        │
  │               │ 303 → /upload │               │
  │               │               │               │
  │ (以降 Cookie 付きでリクエスト)                 │
```

---

## secure_link の仕組み図

```
FastAPI（署名生成）                    Nginx（署名検証）
─────────────────────                  ─────────────────────
expires = 現在時刻 + 3600              受信: ?expires=TS&md5=SIG

raw = expires + uri + SECRET_KEY       raw = $secure_link_expires
    = "1712345678"                          + $uri
      + "/videos/abc/playlist.m3u8"         + SECRET_KEY（envsubstで埋め込み済）
      + "mysecret"

MD5(raw) をバイナリ計算               MD5(raw) を同様に計算
Base64url エンコード（パディングなし） Base64url エンコード

sig = "abc123XYZ..."                   計算値 == $arg_md5 → 200 OK
                                       計算値 != $arg_md5 → 403 Forbidden
URL = /videos/abc/playlist.m3u8        expires < 現在時刻  → 403 Forbidden
    + ?expires=1712345678
    + &md5=abc123XYZ...
```

---

## HLS のディレクトリ構造例

```
/videos/
└── a1b2c3d4-e5f6-7890-abcd-ef1234567890/   ← 動画 UUID
    ├── playlist.m3u8                         ← HLS プレイリスト
    ├── segment000.ts                         ← セグメント 0（0〜4 秒）
    ├── segment001.ts                         ← セグメント 1（4〜8 秒）
    ├── segment002.ts                         ← セグメント 2（8〜12 秒）
    └── ...
```

### playlist.m3u8 の中身（例）

```
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:4.000000,
segment000.ts
#EXTINF:4.000000,
segment001.ts
#EXTINF:3.800000,
segment002.ts
#EXT-X-ENDLIST
```

---

## ディレクトリ構成

```
project/
├── docker-compose.yml      Docker サービス定義
├── .env.example            環境変数のサンプル（.env にコピーして使う）
├── README.md               このファイル
├── nginx/
│   └── nginx.conf          Nginx 設定（envsubst テンプレート）
├── api/
│   ├── Dockerfile          FastAPI コンテナのビルド定義
│   ├── entrypoint.sh       コンテナ起動スクリプト（マイグレーション → uvicorn）
│   ├── requirements.txt    Python 依存パッケージ
│   ├── main.py             FastAPI アプリ本体
│   ├── alembic.ini         Alembic 設定ファイル
│   ├── alembic/
│   │   ├── env.py          マイグレーション環境設定
│   │   ├── script.py.mako  マイグレーションファイルテンプレート
│   │   └── versions/       マイグレーションファイル群
│   └── templates/
│       ├── login.html      ログインページ
│       ├── upload.html     アップロードページ
│       └── player.html     プレイヤーページ（hls.js）
└── videos/
    └── （HLS 出力先: docker volume で管理）
```

---

## 技術スタック

| 用途 | 技術 |
|------|------|
| バックエンド | FastAPI (Python 3.11) |
| 動画変換 | ffmpeg（HLS 単一ビットレート） |
| フロントエンド | Jinja2 テンプレート (HTML) |
| 動画再生 | hls.js |
| 動画配信 | Nginx + secure_link_md5 |
| 認証 | FastAPI Cookie セッション (itsdangerous) |
| データベース | PostgreSQL（動画メタ情報）|
| ORM / マイグレーション | SQLAlchemy 2.x + Alembic |
| コンテナ | Docker Compose（3コンテナ構成） |

---

## 開発環境のセットアップ

### 前提条件

- Docker Desktop または Docker Engine + Docker Compose v2
- Git

### 手順

#### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd minitube
```

#### 2. 環境変数の設定

`.env.example` をコピーして `.env` を作成し、各値を設定する。

```bash
cp .env.example .env
```

`.env` を開いて以下の項目を編集する:

```bash
SECRET_KEY=your_strong_secret_key_here_change_this
ADMIN_PASSWORD=your_password_here
POSTGRES_DB=minitube
POSTGRES_USER=minitube
POSTGRES_PASSWORD=your_postgres_password_here
```

> **注意**: `.env` ファイルはコードに直書きしないこと。Git にコミットしないように `.gitignore` に追加してある。

#### 3. コンテナのビルドと起動

```bash
docker compose up --build
```

#### 4. アクセス

ブラウザで `http://localhost` を開く。

- ログインページ: `http://localhost/login`
- アップロードページ: `http://localhost/upload`（要ログイン）

#### 5. 動画のアップロード

1. `http://localhost/login` でログイン（パスワード: `.env` の `ADMIN_PASSWORD`）
2. `http://localhost/upload` で mp4 ファイルを選択してアップロード
3. ffmpeg が HLS に変換後、プレイヤーページにリダイレクト
4. 動画が再生される

#### 6. コンテナの停止

```bash
docker compose down
```

データ（動画ファイル・DB）を削除する場合:

```bash
docker compose down -v
```

---

## 本番デプロイ手順

### セキュリティ上の必須事項

本番環境では以下を必ず設定・変更すること。

#### 1. 強固なシークレットキーの生成

```bash
# ランダムな 32 バイトの SECRET_KEY を生成する
python3 -c "import secrets; print(secrets.token_hex(32))"
```

#### 2. 環境変数の設定

```bash
export SECRET_KEY="上記で生成した値"
export ADMIN_PASSWORD="強固なパスワード"
export POSTGRES_PASSWORD="強固なパスワード"
export POSTGRES_USER="minitube"
export POSTGRES_DB="minitube"
```

または `.env` ファイルに記載する（Git にコミットしないこと）。

#### 3. HTTPS の設定（本番では必須）

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

#### 4. Nginx のアクセス制御（オプション）

必要に応じて IP アドレス制限を追加する:

```nginx
location /videos/ {
    # IP アドレス制限の例
    allow 192.168.1.0/24;
    deny all;
    # ... secure_link 設定 ...
}
```

#### 5. ディスク容量の監視

動画ファイルは `/volumes/videos_data` に蓄積されるため、定期的な監視・削除が必要。

### デプロイコマンド例

```bash
# 本番サーバで実行
git pull origin main

# 環境変数を設定
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
export ADMIN_PASSWORD="your_production_password"
export POSTGRES_PASSWORD="your_strong_db_password"
export POSTGRES_USER="minitube"
export POSTGRES_DB="minitube"

# ビルドと起動
docker compose up --build -d

# ログ確認
docker compose logs -f
```

---

## API エンドポイント一覧

| メソッド | パス | 説明 | 認証 |
|---------|------|------|------|
| GET | `/` | ルート（/upload へリダイレクト） | - |
| GET | `/login` | ログインページ | 不要 |
| POST | `/api/login` | ログイン処理 | 不要 |
| GET | `/logout` | ログアウト | 不要 |
| GET | `/upload` | アップロードページ | 必要 |
| POST | `/api/upload` | 動画アップロード＆HLS変換 | 必要 |
| GET | `/player/{id}` | プレイヤーページ | 必要 |
| GET | `/api/videos/{id}/url` | 署名付き HLS URL 取得 | 必要 |

---

## トラブルシューティング

### 動画が再生されない

1. ブラウザの開発者ツールのネットワークタブで `/videos/*.m3u8` のレスポンスを確認
2. 403 が返る場合: SECRET_KEY が FastAPI と Nginx で一致しているか確認
3. ffmpeg の変換ログを確認: `docker compose logs api`

### ffmpeg の変換が失敗する

mp4 ファイルのコーデックが H.264/AAC でない場合、変換に時間がかかるか失敗することがある。

```bash
# コンテナ内でログを確認
docker compose logs api --tail=50
```

### Nginx の設定確認

```bash
# Nginx コンテナに入って設定を確認
docker compose exec nginx nginx -t
docker compose exec nginx cat /etc/nginx/nginx.conf
```
