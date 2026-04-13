# minitube

最小構成の動画配信 Web アプリ。mp4 をアップロードすると HLS に変換し、RBAC によるロールベースのアクセス制御で動画の公開・非公開を管理できる。

---

## 概要

このアプリは「製品化」ではなく、動画配信の仕組みを理解するための最小構成を目的とする。

- **認証**: FastAPI の Cookie セッション（メールアドレス + bcrypt パスワード認証）
- **RBAC**: admin / uploader / viewer の 3 ロールによるアクセス制御
- **変換**: Worker コンテナが ffmpeg で mp4 → HLS（playlist.m3u8 + segment*.ts）に非同期変換
- **キュー**: Redis Queue で API から Worker へ変換ジョブを受け渡す
- **保存**: Worker が変換後の HLS ファイルを **MinIO**（S3 互換オブジェクトストレージ）に永続保存
- **配信**: Nginx が secure_link_md5 検証後に **MinIO へ直接 proxy_pass**（proxy_cache 付き）
- **保護**: 署名付きURL（1 時間有効）。公開動画は未ログインでも視聴可能。非公開動画は権限保有者のみ視聴可能

---

## ユーザ管理・RBAC 仕様

### ロール

| ロール | 説明 |
|--------|------|
| `admin` | 全機能にアクセス可能。ユーザ管理・全動画管理 |
| `uploader` | 動画のアップロードが可能 |
| `viewer` | 動画の視聴のみ可能（新規登録ユーザはこのロール） |

### 動画の公開設定

| 設定 | 説明 |
|------|------|
| `public` | 未ログインを含む全員が視聴可能 |
| `private` | admin・オーナー・権限付与されたユーザのみ視聴可能 |

### 初期管理者ユーザ

起動時に `admin@example.com` ユーザが自動作成される（`INITIAL_ADMIN_PASSWORD` 環境変数で設定）。
パスワードは初回起動時のみ設定され、再起動時には更新されない（冪等性）。

### VideoPermission（動画視聴権限）

非公開動画に対して、admin またはオーナーが特定ユーザに視聴権限を付与できる。
プレイヤーページ（`/player/{id}`）の権限管理セクションから操作可能。

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
│  /api/*    → FastAPI へ proxy │
│  /videos/  → secure_link 検証 │
│             → MinIO proxy_pass│
│             → proxy_cache     │
└──────┬──────────┬────────────┘
       │          │ proxy_pass (secure_link 検証済)
       │ proxy    ▼
       │  ┌──────────────────────────────┐
       │  │       MinIO コンテナ           │
       │  │                               │
       │  │  バケット: minitube            │
       │  │  hls/{video_id}/playlist.m3u8 │
       │  │  hls/{video_id}/segment*.ts   │
       │  └──────────────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│       FastAPI コンテナ        │
│                               │
│  /login    ログインページ     │
│  /upload   アップロード       │
│  /player/  プレイヤーページ  │
│  /api/...  認証・署名・状態  │
│  /api/videos/{id}/playlist   │
│    MinIO から m3u8 を取得し  │
│    署名付きセグメントURLを埋込│
│                               │
│  SQLAlchemy: DB アクセス      │
│  redis-py: ジョブ enqueue    │
│  boto3: MinIO 読み込み        │
└──────┬──────┬────────────────┘
       │      │
       │ Vol  │ RPUSH job_id
       │      ▼
       │  ┌───────────────────┐
       │  │   Redis コンテナ   │
       │  │  split_jobs キュー │
       │  └────────┬──────────┘
       │           │ BLPOP
       │           ▼
       │  ┌──────────────────────────┐
       │  │     Worker コンテナ       │
       │  │                           │
       │  │  ffmpeg: mp4 → HLS 変換  │
       │  │  boto3: MinIO にアップロード│
       │  │  DB: ジョブ状態を UPDATE  │
       │  └────────┬─────────────────┘
       │           │ boto3 upload
       │           ▼
       │  ┌──────────────────────────────┐
       │  │       MinIO コンテナ           │
       │  │  hls/{video_id}/playlist.m3u8 │
       │  │  hls/{video_id}/segment*.ts   │
       │  └──────────────────────────────┘
       │
       ▼
┌──────────────────────┐  ┌─────────────────────────────┐
│  /videos (共有 Vol)  │  │    PostgreSQL コンテナ（db）  │
│                       │  │                               │
│  input.mp4 のみ一時   │  │  videos テーブル              │
│  保存（変換後削除）   │  │  id, title, created_at        │
│  HLS は MinIO に保存  │  │                               │
└──────────────────────┘  │  jobs テーブル                │
                           │  id, video_id, type, status   │
                           └─────────────────────────────┘
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

## secure_link の仕組みと署名仕様

### 署名仕様（Nginx secure_link_md5 と同一）

```
secure_link_md5 "$secure_link_expires${uri}${SECRET_KEY}";
```

FastAPI と Nginx は同じ計算式で署名を生成・検証する:

| 要素 | 説明 |
|------|------|
| `expires` | UNIX タイムスタンプ（現在時刻 + 3600 秒） |
| `uri` | クエリを含まないパス（例: `/videos/abc/segment000.ts`） |
| `SECRET_KEY` | 環境変数から注入（コミット禁止） |

```
raw_string = expires + uri + SECRET_KEY
signature  = base64url_nopad( MD5( raw_string.encode('utf-8') ) )
```

### 署名フロー図

```
FastAPI（署名生成）                    Nginx（署名検証）
─────────────────────                  ─────────────────────
expires = 現在時刻 + 3600              受信: ?expires=TS&md5=SIG

raw = expires + uri + SECRET_KEY       raw = $secure_link_expires
    = "1712345678"                          + $uri
      + "/videos/abc/segment000.ts"         + SECRET_KEY（envsubstで埋め込み済）
      + "mysecret"

MD5(raw) をバイナリ計算               MD5(raw) を同様に計算
Base64url エンコード（パディングなし） Base64url エンコード

sig = "abc123XYZ..."                   計算値 == $arg_md5 → MinIO へ proxy
                                       計算値 != $arg_md5 → 403 Forbidden
URL = /videos/abc/segment000.ts        expires < 現在時刻  → 403 Forbidden
    + ?expires=1712345678
    + &md5=abc123XYZ...
```

---

## MinIO のオブジェクトキー規約

HLS ファイルは以下のキーで MinIO バケット（デフォルト: `minitube`）に保存される:

```
hls/{video_id}/playlist.m3u8
hls/{video_id}/segment000.ts
hls/{video_id}/segment001.ts
...
```

Nginx の URI から MinIO パスへの対応:

| Nginx リクエスト URI | MinIO オブジェクトキー |
|---------------------|----------------------|
| `/videos/{id}/segment000.ts` | `hls/{id}/segment000.ts` |
| `/videos/{id}/segment001.ts` | `hls/{id}/segment001.ts` |

---

## Nginx proxy_cache の意図と注意点

### キャッシュの目的

Nginx は secure_link 検証後に MinIO へ proxy_pass し、レスポンスをローカルキャッシュに保存する。  
同一セグメントへの繰り返しアクセスは MinIO への upstream リクエストを省略できる。

### キャッシュキー方針（重要）

```nginx
proxy_cache_key "$scheme$proxy_host$uri";
```

**クエリパラメータ（`expires`/`md5`）をキャッシュキーから除外**している。  
これにより有効期限や署名値が変わっても、同一セグメントファイルは同一キャッシュエントリにヒットする。

**安全性の根拠**:
- `expires`/`md5` の検証は secure_link が担当し、403 は proxy_cache に到達する前に返される
- キャッシュに到達するのは検証通過済みリクエストのみ
- キャッシュキーからクエリを除外しても、不正なリクエストがキャッシュヒットすることはない

### キャッシュ状態の確認

レスポンスの `X-Cache-Status` ヘッダでキャッシュ状態を確認できる:

| 値 | 意味 |
|----|------|
| `MISS` | キャッシュなし（MinIO から取得） |
| `HIT` | キャッシュヒット（MinIO へのアクセスなし） |
| `EXPIRED` | キャッシュ期限切れ（MinIO から再取得） |

```bash
# キャッシュ確認例
curl -v "http://localhost/videos/{id}/segment000.ts?expires=...&md5=..." 2>&1 | grep X-Cache-Status
```

---

## HLS のディレクトリ構造例（MinIO 移行後）

MinIO バケット（`minitube`）内のオブジェクト:

```
hls/
└── a1b2c3d4-e5f6-7890-abcd-ef1234567890/   ← 動画 UUID
    ├── playlist.m3u8                         ← HLS プレイリスト
    ├── segment000.ts                         ← セグメント 0（0〜4 秒）
    ├── segment001.ts                         ← セグメント 1（4〜8 秒）
    ├── segment002.ts                         ← セグメント 2（8〜12 秒）
    └── ...
```

ローカルの `/videos` ボリュームには `input.mp4` のみ一時的に保存され、変換後に削除される。

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

FastAPI の `/api/videos/{id}/playlist` が上記を MinIO から読み込み、各セグメント行を署名付き URI に書き換えて返す:

```
#EXTINF:4.000000,
/videos/{id}/segment000.ts?expires=1712345678&md5=abc123XYZ...
```

---

## ディレクトリ構成

```
project/
├── docker-compose.yml      Docker サービス定義（7コンテナ構成）
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
│       ├── upload.html     アップロードページ（ジョブ状態ポーリング付き）
│       └── player.html     プレイヤーページ（hls.js・ジョブ状態ポーリング付き）
├── worker/
│   ├── Dockerfile          Worker コンテナのビルド定義（ffmpeg 含む）
│   ├── worker_split.py     Redis Queue 監視・HLS 変換オーケストレーション
│   ├── jobs/
│   │   └── split.py        ffmpeg HLS 変換・MinIO アップロード処理
│   └── utils/
│       └── db.py           DB アクセスユーティリティ（ジョブ状態 UPDATE）
└── videos/
    └── （input.mp4 一時保存のみ: docker volume で管理）
```

---

## 技術スタック

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
# セッション・署名用シークレット（必須: 強固な値に変更すること）
SECRET_KEY=your_strong_secret_key_here_change_this

# 初期管理者パスワード（初回起動時に admin@example.com ユーザに設定）
# 再起動時には更新されない
INITIAL_ADMIN_PASSWORD=your_admin_password_here

# PostgreSQL 接続情報
POSTGRES_DB=minitube
POSTGRES_USER=minitube
POSTGRES_PASSWORD=your_postgres_password_here

# MinIO 認証情報
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=your_minio_secret_here
MINIO_BUCKET=minitube
```

> **注意**: `.env` ファイルはコードに直書きしないこと。Git にコミットしないように `.gitignore` に追加してある。

#### 3. コンテナのビルドと起動

```bash
docker compose up --build
```

起動順序:
1. `db`（PostgreSQL）、`redis`、`minio` が起動する
2. `createbuckets` が MinIO にバケットを作成して終了する
3. `api`（FastAPI）と `worker` が起動する
4. `nginx` が起動する

起動時に `api` コンテナが自動で以下を実行する（冪等）:
- `admin` / `uploader` / `viewer` ロールを作成
- `admin@example.com` ユーザを作成（パスワード: `INITIAL_ADMIN_PASSWORD`）
- `admin@example.com` に `admin` ロールを付与

#### 4. アクセス

ブラウザで `http://localhost` を開く。

- 動画一覧ページ: `http://localhost/videos`（未ログインでも公開動画を閲覧可）
- ログインページ: `http://localhost/login`
- 新規登録ページ: `http://localhost/register`
- アップロードページ: `http://localhost/upload`（uploader または admin ロール必須）

#### 5. MinIO コンソールの確認

MinIO の Web コンソールで保存されたファイルを確認できる:

```
http://localhost:9001
```

- ユーザ名: `.env` の `MINIO_ACCESS_KEY`（デフォルト: `minioadmin`）
- パスワード: `.env` の `MINIO_SECRET_KEY`

動画のアップロード・変換完了後、バケット（`minitube`）の `hls/` プレフィックス下にファイルが保存されているはず。

#### 6. UI の使い方

**管理者 (admin@example.com) として:**
1. `http://localhost/login` でメールアドレスとパスワードを入力してログイン
2. 動画一覧 `/videos` が表示される
3. `/upload` でアップロードページへ（mp4 を選択し公開設定を選択してアップロード）
4. `/admin/users` でユーザ一覧と各ユーザのロール管理

**新規ユーザの登録:**
1. `/register` でメールアドレス・パスワードを入力して登録（自動的に `viewer` ロール付与）
2. `/login` でログイン
3. `viewer` ロールでは動画視聴のみ可能（アップロード不可）
4. 管理者が `/admin/users` から `uploader` ロールを付与すると動画アップロードが可能になる

**非公開動画の視聴権限付与:**
1. 非公開動画のプレイヤーページ（`/player/{id}`）を開く
2. 権限管理セクション（admin またはオーナーのみ表示）にメールアドレスを入力して「権限付与」
3. 付与したユーザはその動画をログイン後に視聴可能になる

#### 7. コンテナの停止

```bash
docker compose down
```

データ（動画ファイル・DB・MinIO）を削除する場合:

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
export INITIAL_ADMIN_PASSWORD="強固なパスワード"
export POSTGRES_PASSWORD="強固なパスワード"
export POSTGRES_USER="minitube"
export POSTGRES_DB="minitube"
export MINIO_ACCESS_KEY="強固なアクセスキー"
export MINIO_SECRET_KEY="強固なシークレットキー"
export MINIO_BUCKET="minitube"
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

---

## API エンドポイント一覧

| メソッド | パス | 説明 | 認証 |
|---------|------|------|------|
| GET | `/` | ルート（/videos へリダイレクト） | - |
| GET | `/login` | ログインページ | 不要 |
| POST | `/api/login` | ログイン処理 | 不要 |
| GET | `/logout` | ログアウト | 不要 |
| GET | `/register` | ユーザ登録ページ | 不要 |
| POST | `/api/register` | ユーザ登録 | 不要 |
| GET | `/videos` | 動画一覧ページ | 不要（公開動画） |
| GET | `/upload` | アップロードページ | 必要（uploader/admin） |
| POST | `/api/upload` | 動画アップロード → 編集画面へリダイレクト | 必要（uploader/admin） |
| GET | `/videos/{id}/edit` | 動画編集ページ | 必要（オーナー/admin） |
| POST | `/api/videos/{id}/update` | 動画メタ情報更新（title/description/category/visibility） | 必要（オーナー/admin） |
| POST | `/api/videos/{id}/delete` | 動画削除（HLS・DB レコード削除） | 必要（オーナー/admin） |
| POST | `/api/videos/{id}/replace` | 動画ファイル差し替え（HLS 再生成） | 必要（オーナー/admin） |
| GET | `/player/{id}` | プレイヤーページ | 必要（公開動画は不要） |
| GET | `/api/job/{job_id}` | ジョブ状態取得（queued/processing/completed/error） | 不要 |
| GET | `/api/videos/{id}/url` | 署名付き HLS URL 取得（`/api/videos/{id}/playlist` を指す） | 必要 |
| GET | `/api/videos/{id}/playlist` | MinIO から playlist.m3u8 を取得し署名付きセグメント URL を埋め込んで返す | 必要 |
| GET | `/videos/{id}/*.ts` | Nginx が secure_link 検証後 MinIO から TS セグメントを返す（FastAPI 経由なし） | 不要（署名） |
| GET | `/profile` | プロフィールページ | 必要 |
| GET | `/admin/users` | Admin 専用ユーザ管理ページ | 必要（admin） |
| POST | `/api/admin/users/{id}/roles` | ロール付与 | 必要（admin） |
| POST | `/api/admin/users/{id}/roles/{role}/delete` | ロール削除 | 必要（admin） |
| POST | `/api/admin/videos/{id}/permissions` | 動画視聴権限付与 | 必要（admin/オーナー） |
| POST | `/api/admin/videos/{id}/permissions/{uid}/delete` | 動画視聴権限削除 | 必要（admin/オーナー） |
| GET | `/admin/categories` | カテゴリ管理ページ | 必要（admin） |
| POST | `/api/admin/categories` | カテゴリ作成 | 必要（admin） |
| POST | `/api/admin/categories/{id}/update` | カテゴリ名変更 | 必要（admin） |
| POST | `/api/admin/categories/{id}/delete` | カテゴリ削除（動画紐付きは不可） | 必要（admin） |

---

## 動画メタ情報仕様

### videos テーブルのカラム

| カラム | 型 | 説明 |
|--------|-----|------|
| `id` | VARCHAR | 動画の一意識別子（UUID v4） |
| `title` | VARCHAR | タイトル |
| `description` | VARCHAR | 説明（任意） |
| `category_id` | VARCHAR | カテゴリ ID（FK → categories.id, ON DELETE SET NULL） |
| `visibility` | VARCHAR | 公開設定（`public` / `private`） |
| `status` | VARCHAR | 変換ステータス（`processing` / `ready` / `failed`） |
| `owner_user_id` | VARCHAR | オーナーユーザ ID（FK → users.id） |
| `created_at` | BIGINT | 作成日時（UNIX タイムスタンプ） |
| `updated_at` | BIGINT | 更新日時（UNIX タイムスタンプ） |

### categories テーブルのカラム

| カラム | 型 | 説明 |
|--------|-----|------|
| `id` | VARCHAR | カテゴリの一意識別子（UUID v4） |
| `name` | VARCHAR | カテゴリ名（ユニーク） |
| `created_at` | BIGINT | 作成日時（UNIX タイムスタンプ） |

### 動画ステータスの遷移

```
アップロード → processing → ready（変換成功）
                          → failed（変換失敗）
差し替え     → processing → ready / failed
```

---

## 動画アップロード → 編集画面への遷移フロー

1. Uploader が `/upload` から mp4 をアップロード
2. `video_id`（UUID）が発行され、`videos.status = "processing"` に設定
3. HLS 変換ジョブが Redis Queue に登録される（`jobs.status = "queued"`）
4. **動画編集画面 `/videos/{video_id}/edit` へ自動遷移**
5. 編集画面でタイトル・説明・カテゴリ・公開設定を入力・保存
6. Worker が HLS 変換完了後、`videos.status = "ready"` に更新
7. 編集画面のステータスバッジが自動更新され「▶ 再生する」リンクが表示される

---

## トラブルシューティング

### 動画が再生されない

1. ブラウザの開発者ツールのネットワークタブで `/api/videos/{id}/playlist` のレスポンスを確認
2. セグメントリクエスト（`/videos/{id}/*.ts`）が 403 を返す場合: SECRET_KEY が FastAPI と Nginx で一致しているか確認
3. Worker の変換・アップロードログを確認: `docker compose logs worker`

### MinIO にファイルが保存されない

```bash
# Worker のログを確認（アップロードエラーの詳細が出る）
docker compose logs worker --tail=50

# MinIO の状態を確認
docker compose logs minio --tail=20

# MinIO コンソールで確認
open http://localhost:9001
```

### ffmpeg の変換が失敗する

mp4 ファイルのコーデックが H.264/AAC でない場合、変換に時間がかかるか失敗することがある。

```bash
# Worker コンテナのログを確認
docker compose logs worker --tail=50
```

### ジョブが queued のまま進まない

Worker コンテナが正常に起動しているか確認する。

```bash
docker compose ps
docker compose logs worker --tail=50
```

### Nginx の設定確認

```bash
# Nginx コンテナに入って設定を確認
docker compose exec nginx nginx -t
docker compose exec nginx cat /etc/nginx/nginx.conf

# Nginx のアクセスログでキャッシュ状態を確認
docker compose logs nginx --tail=50
```
