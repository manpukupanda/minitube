# アーキテクチャ

## コンテナ構成図

```
ブラウザ
   │
   │ HTTP (ポート 80)
   ▼
┌─────────────────────────────┐
│         Nginx コンテナ        │
│                               │
│  /api/*        → FastAPI へ proxy │
│  /videos/      → secure_link 検証 │
│                 → MinIO proxy_pass│
│                 → proxy_cache     │
│  /thumbnails/  → MinIO proxy_pass │
│  /user-icons/  → MinIO proxy_pass │
│  /hero-images/ → MinIO proxy_pass │
└──────┬──────────┬────────────┘
       │          │ proxy_pass (secure_link 検証済 / 直接)
       │ proxy    ▼
       │  ┌──────────────────────────────┐
       │  │       MinIO コンテナ           │
       │  │                               │
       │  │  バケット: minitube            │
       │  │  hls/{video_id}/playlist.m3u8 │
       │  │  hls/{video_id}/segment*.ts   │
       │  │  videos/{video_id}/thumbnails/│
       │  │    {thumbnail_id}.jpg         │
│  │  user-icons/{user_id}.{ext}     │
│  │  hero-images/{id}.{ext}         │
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
       │  │  ffmpeg: サムネイル生成   │
       │  │  boto3: MinIO にアップロード│
       │  │  DB: ジョブ状態を UPDATE  │
       │  └────────┬─────────────────┘
       │           │ boto3 upload
       │           ▼
       │  ┌──────────────────────────────┐
       │  │       MinIO コンテナ           │
       │  │  hls/{video_id}/playlist.m3u8 │
       │  │  hls/{video_id}/segment*.ts   │
       │  │  videos/{video_id}/thumbnails/│
       │  │    {thumbnail_id}.jpg         │
       │  └──────────────────────────────┘
       │
       ▼
┌──────────────────────┐  ┌─────────────────────────────┐
│  /videos (共有 Vol)  │  │    PostgreSQL コンテナ（db）  │
│                       │  │                               │
│  input.mp4 のみ一時   │  │  videos テーブル              │
│  保存（変換後削除）   │  │  id, title, created_at        │
│  HLS はMinIOに保存  │  │                               │
└──────────────────────┘  │  jobs テーブル                │
                           │  id, video_id, type, status   │
                           │                               │
                           │  thumbnails テーブル           │
                           │  id, video_id, url, type,     │
                           │  active, created_at            │
                           │                               │
                           │  watch_history テーブル        │
                           │  user_id, video_id,           │
                           │  last_watched_at,             │
                           │  last_position, duration,     │
                           │  completed                    │
                           └─────────────────────────────┘
```

## 各コンテナの役割

| コンテナ | 役割 |
|---------|------|
| `nginx` | リバースプロキシ。secure_link 検証、MinIO への proxy_pass、proxy_cache |
| `api` | FastAPI。認証・動画管理・署名付き URL 生成 |
| `worker` | ffmpeg HLS 変換・サムネイル生成・MinIO アップロード |
| `db` | PostgreSQL。動画・ジョブ・ユーザ情報の永続化 |
| `redis` | Redis。変換ジョブキュー（`split_jobs`） |
| `minio` | MinIO（S3 互換）。HLS ファイル・サムネイル・アイコンの永続保存 |
| `createbuckets` | 初回起動時に MinIO バケットを作成して終了 |

## ディレクトリ構成

```
project/
├── docker-compose.yml      Docker サービス定義（7コンテナ構成）
├── .env.example            環境変数のサンプル（.env にコピーして使う）
├── README.md               このファイル
├── docs/                   詳細ドキュメント
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
│       ├── home.html           ホーム画面（視聴者向け動画タイル一覧）
│       ├── login.html          ログインページ
│       ├── register.html       新規登録ページ
│       ├── upload.html         アップロードページ（ジョブ状態ポーリング付き）
│       ├── player.html         プレイヤーページ（hls.js・ジョブ状態ポーリング付き）
│       ├── videos.html         動画管理一覧ページ（テーブル形式）
│       ├── video_edit.html     動画編集ページ
│       ├── profile.html        プロフィール編集ページ
│       ├── admin_users.html    Admin 専用ユーザ管理ページ
│       ├── admin_categories.html    Admin 専用カテゴリ管理ページ
│       ├── admin_tags.html      Admin 専用タグ管理ページ
│       ├── tags.html            タグ別動画一覧ページ
│       ├── search.html          検索結果ページ
│       └── admin_site_settings.html Admin 専用ホーム画面設定ページ
├── worker/
│   ├── Dockerfile          Worker コンテナのビルド定義（ffmpeg 含む）
│   ├── worker_split.py     Redis Queue 監視・HLS 変換オーケストレーション
│   ├── jobs/
│   │   └── split.py        ffmpeg HLS 変換・サムネイル生成・MinIO アップロード・Nginx キャッシュ削除
│   └── utils/
│       ├── db.py           DB アクセスユーティリティ（ジョブ状態 UPDATE・サムネイル INSERT）
│       ├── id_generator.py Base62 ID 生成ユーティリティ（Worker 用）
│       └── nginx_cache.py  Nginx キャッシュ削除ユーティリティ（MD5 パス逆算）
└── videos/
    └── （input.mp4 一時保存のみ: docker volume で管理）
```

## API エンドポイント一覧

| メソッド | パス | 説明 | 認証 |
|---------|------|------|------|
| GET | `/` | ルート（/home へリダイレクト） | - |
| GET | `/home` | ホーム画面（視聴者向け動画一覧） | 不要（公開動画） |
| GET | `/search` | 検索結果ページ（タイトル・説明・タグ・カテゴリを検索） | 必要 |
| GET | `/login` | ログインページ | 不要 |
| POST | `/api/login` | ログイン処理 | 不要 |
| GET | `/logout` | ログアウト | 不要 |
| GET | `/register` | ユーザ登録ページ | 不要 |
| POST | `/api/register` | ユーザ登録 | 不要 |
| GET | `/videos` | 動画一覧ページ | 不要（公開動画） |
| GET | `/upload` | アップロードページ | 必要（uploader/admin） |
| POST | `/api/upload` | 動画アップロード → 編集画面へリダイレクト | 必要（uploader/admin） |
| GET | `/videos/{id}/edit` | 動画編集ページ | 必要（オーナー/admin） |
| POST | `/api/videos/{id}/update` | 動画メタ情報更新（title/description/category/tags/visibility） | 必要（オーナー/admin） |
| POST | `/api/videos/{id}/delete` | 動画削除（HLS・DB レコード削除） | 必要（オーナー/admin） |
| POST | `/api/videos/{id}/replace` | 動画ファイル差し替え（HLS 再生成） | 必要（オーナー/admin） |
| POST | `/api/videos/{id}/clear_cache` | Nginx HLS キャッシュ削除 | 必要（オーナー/admin） |
| POST | `/api/videos/{id}/thumbnails/{thumb_id}/activate` | サムネイルの切り替え（active 設定） | 必要（オーナー/admin） |
| GET | `/player/{id}` | プレイヤーページ | 必要（公開動画は不要） |
| GET | `/api/job/{job_id}` | ジョブ状態取得（queued/processing/completed/error） | 不要 |
| GET | `/api/videos/{id}/url` | 署名付き HLS URL 取得（`/api/videos/{id}/playlist` を指す） | 必要 |
| GET | `/api/videos/{id}/playlist` | MinIO から playlist.m3u8 を取得し署名付きセグメント URL を埋め込んで返す | 必要 |
| GET | `/videos/{id}/*.ts` | Nginx が secure_link 検証後 MinIO から TS セグメントを返す（FastAPI 経由なし） | 不要（署名） |
| GET | `/profile` | プロフィールページ | 必要 |
| GET | `/notifications` | 通知一覧ページ | 必要 |
| GET | `/admin/users` | Admin 専用ユーザ管理ページ | 必要（admin） |
| POST | `/api/admin/users/{id}/roles` | ロール付与 | 必要（admin） |
| POST | `/api/admin/users/{id}/roles/{role}/delete` | ロール削除 | 必要（admin） |
| POST | `/api/admin/notifications` | 管理者通知を作成（全ユーザ or 特定ロール） | 必要（admin） |
| POST | `/api/admin/videos/{id}/permissions` | 動画視聴権限付与 | 必要（admin/オーナー） |
| POST | `/api/admin/videos/{id}/permissions/{uid}/delete` | 動画視聴権限削除 | 必要（admin/オーナー） |
| GET | `/admin/categories` | カテゴリ管理ページ | 必要（admin） |
| POST | `/api/admin/categories` | カテゴリ作成 | 必要（admin） |
| POST | `/api/admin/categories/{id}/update` | カテゴリ名変更 | 必要（admin） |
| POST | `/api/admin/categories/{id}/delete` | カテゴリ削除（動画紐付きは不可） | 必要（admin） |
| GET | `/admin/tags` | タグ管理ページ | 必要（admin） |
| GET | `/tags/{slug}` | タグ別動画一覧ページ | 不要（公開動画） |
| GET | `/api/tags` | タグ一覧取得 | 不要 |
| GET | `/api/tags/{slug}` | タグ情報 + 動画一覧取得 | 不要 |
| GET | `/api/search?q=...` | 検索 API（タイトル・説明・タグ・カテゴリ、created_at 降順） | 必要 |
| POST | `/api/admin/tags` | タグ作成 | 必要（admin） |
| PUT | `/api/admin/tags/{id}` | タグ名変更（slug 自動更新） | 必要（admin） |
| DELETE | `/api/admin/tags/{id}` | タグ削除（動画紐付きは 400） | 必要（admin） |
| PUT | `/api/admin/videos/{id}/tags` | 動画へのタグ付与更新（`{ tag_ids: [] }`） | 必要（admin） |
| GET | `/api/site_settings` | 公開用ホーム画面設定取得（top_notice / hero_image_url / recommended_video_ids） | 不要 |
| GET | `/admin/site-settings` | ホーム画面設定ページ | 必要（admin） |
| POST | `/api/admin/site_settings` | ホーム画面設定更新（お知らせ / ヒーロー画像 / おすすめ動画） | 必要（admin） |
| POST | `/api/videos/{id}/watch` | 再生開始時に視聴履歴を作成・更新 | 必要 |
| POST | `/api/videos/{id}/progress` | 再生位置・動画長を更新（JSON: position, duration） | 必要 |
| POST | `/api/videos/{id}/complete` | 視聴完了を記録 | 必要 |
| GET | `/api/users/me/history` | 最近見た動画一覧（last_watched_at 降順） | 必要 |
| GET | `/api/users/me/resume` | 続きから再生できる動画一覧（last_position > 0） | 必要 |
| POST | `/api/videos/{id}/favorite` | お気に入り追加（登録済みでも 200） | 必要 |
| DELETE | `/api/videos/{id}/favorite` | お気に入り解除（未登録でも 200） | 必要 |
| GET | `/api/users/me/favorites` | お気に入り一覧（created_at 降順） | 必要 |
| POST | `/api/videos/{id}/watch_later` | 後で見る追加（登録済みでも 200） | 必要 |
| DELETE | `/api/videos/{id}/watch_later` | 後で見る解除（未登録でも 200） | 必要 |
| GET | `/api/users/me/watch_later` | 後で見る一覧（created_at 降順、auto_removed_at IS NULL） | 必要 |
| GET | `/api/users/me/notifications` | 通知一覧取得（`unread_only=true` で未読のみ） | 必要 |
| POST | `/api/notifications/{id}/read` | 単一通知を既読化（冪等） | 必要 |
| POST | `/api/notifications/read_all` | 自分の通知をすべて既読化 | 必要 |

## データベーススキーマ

### videos テーブル

| カラム | 型 | 説明 |
|--------|-----|------|
| `id` | CHAR(11) | 動画の一意識別子（Base62 11文字） |
| `title` | VARCHAR | タイトル |
| `description` | VARCHAR | 説明（任意） |
| `category_id` | CHAR(11) | カテゴリ ID（FK → categories.id, ON DELETE SET NULL） |
| `visibility` | VARCHAR | 公開設定（`public` / `private`） |
| `status` | VARCHAR | 変換ステータス（`processing` / `ready` / `failed`） |
| `owner_user_id` | VARCHAR | オーナーユーザ ID（FK → users.id） |
| `created_at` | BIGINT | 作成日時（UNIX タイムスタンプ） |
| `updated_at` | BIGINT | 更新日時（UNIX タイムスタンプ） |

### categories テーブル

| カラム | 型 | 説明 |
|--------|-----|------|
| `id` | CHAR(11) | カテゴリの一意識別子（Base62 11文字） |
| `name` | VARCHAR | カテゴリ名（ユニーク） |
| `created_at` | BIGINT | 作成日時（UNIX タイムスタンプ） |

### tags テーブル（マイグレーション: `c2d3e4f5g6h7`）

| カラム | 型 | 説明 |
|--------|-----|------|
| `id` | CHAR(11) | タグの一意識別子（Base62 11文字） |
| `name` | VARCHAR | タグ名（ユニーク） |
| `slug` | VARCHAR | URL 用スラッグ（ユニーク） |
| `created_at` | BIGINT | 作成日時（UNIX タイムスタンプ） |

### video_tags テーブル（マイグレーション: `c2d3e4f5g6h7`）

| カラム | 型 | 説明 |
|--------|-----|------|
| `video_id` | CHAR(11) | FK → videos.id（ON DELETE CASCADE、PK の一部） |
| `tag_id` | CHAR(11) | FK → tags.id（ON DELETE RESTRICT、PK の一部） |

主キーは `(video_id, tag_id)`。  
動画には複数タグを付与でき、タグは複数動画に紐づく（多対多）。

### thumbnails テーブル（マイグレーション: `6f7g8h9i0j1k`）

| カラム | 型 | NULL 許可 | 説明 |
|--------|-----|----------|------|
| `id` | CHAR(11) | - | サムネイルの一意識別子（Base62 11文字、PK） |
| `video_id` | CHAR(11) | - | FK → videos.id（ON DELETE CASCADE） |
| `url` | TEXT | - | Nginx 経由のサムネイル URL（`/thumbnails/{video_id}/{id}.jpg`） |
| `type` | VARCHAR | - | サムネイル種別（`fixed` / `representative` / `custom`） |
| `active` | BOOLEAN | - | 選択中のサムネイル（`true` は常に1件） |
| `created_at` | BIGINT | - | 作成日時（UNIX タイムスタンプ） |

#### サムネイル種別

| `type` | 生成タイミング | 説明 |
|--------|------------|------|
| `fixed` | HLS 変換後に自動生成 | 5 秒地点のフレーム（duration < 5 秒の場合は duration/2） |
| `representative` | HLS 変換後に自動生成 | ffmpeg の `thumbnail` フィルタが選んだ代表フレーム |
| `custom` | 将来的なユーザアップロード用 | 現在は未実装 |

### watch_history テーブル（マイグレーション: `7g8h9i0j1k2l`）

| カラム | 型 | NULL 許可 | 説明 |
|--------|-----|----------|------|
| `user_id` | VARCHAR | - | FK → users.id（PK の一部） |
| `video_id` | VARCHAR | - | FK → videos.id（ON DELETE CASCADE、PK の一部） |
| `last_watched_at` | BIGINT | - | 最後に視聴した日時（UNIX タイムスタンプ） |
| `last_position` | INTEGER | - | 最後に視聴した再生位置（秒）、デフォルト 0 |
| `duration` | INTEGER | 許可 | 動画の長さ（秒）、初回 progress で保存 |
| `completed` | BOOLEAN | - | 視聴完了フラグ、デフォルト false |

主キーは `(user_id, video_id)` のため、1 ユーザにつき 1 動画の履歴が 1 行にまとまる。  
動画削除時は `ON DELETE CASCADE` で履歴も自動削除される。

### favorites テーブル（マイグレーション: `8h9i0j1k2l3m`）

| カラム | 型 | NULL 許可 | 説明 |
|--------|-----|----------|------|
| `user_id` | VARCHAR | - | FK → users.id（PK の一部） |
| `video_id` | VARCHAR | - | FK → videos.id（ON DELETE CASCADE、PK の一部） |
| `created_at` | BIGINT | - | お気に入り登録日時（UNIX タイムスタンプ） |

主キーは `(user_id, video_id)` のため重複登録は不可。  
動画削除時は `ON DELETE CASCADE` で favorites も自動削除される。

### watch_later テーブル（マイグレーション: `9i0j1k2l3m4n`）

| カラム | 型 | NULL 許可 | 説明 |
|--------|-----|----------|------|
| `user_id` | VARCHAR | - | FK → users.id（PK の一部） |
| `video_id` | VARCHAR | - | FK → videos.id（ON DELETE CASCADE、PK の一部） |
| `created_at` | BIGINT | - | 後で見る登録日時（UNIX タイムスタンプ） |
| `auto_removed_at` | BIGINT | 許可 | 自動削除日時（将来拡張用、現状未使用） |

主キーは `(user_id, video_id)` のため重複登録は不可。  
動画削除時は `ON DELETE CASCADE` で watch_later も自動削除される。

### notifications テーブル（マイグレーション: `a0b1c2d3e4f5`）

| カラム | 型 | NULL 許可 | 説明 |
|--------|-----|----------|------|
| `id` | CHAR(11) | - | 通知 ID（PK） |
| `user_id` | VARCHAR | - | 通知対象ユーザ（FK → users.id） |
| `type` | VARCHAR | - | 通知種別（`new_video` / `video_updated` / `permission_granted` / `admin_message`） |
| `title` | VARCHAR | - | 通知タイトル |
| `message` | TEXT | - | 通知本文 |
| `video_id` | VARCHAR | 許可 | 関連動画（FK → videos.id, ON DELETE SET NULL） |
| `created_at` | BIGINT | - | 作成日時（UNIX タイムスタンプ） |
| `read_at` | BIGINT | 許可 | 既読日時（未読時は NULL） |

`read_at IS NULL` を未読として扱う。  
動画削除時は `video_id` が `NULL` になり、通知履歴自体は保持される。

### site_settings テーブル（マイグレーション: `b1c2d3e4f5g6`）

| カラム | 型 | NULL 許可 | 説明 |
|--------|-----|----------|------|
| `id` | INTEGER | - | 設定レコード ID（単一レコード運用） |
| `top_notice` | TEXT | 許可 | ホーム上部のお知らせテキスト（複数行） |
| `hero_image_url` | TEXT | 許可 | Nginx 経由で配信するヒーロー画像 URL（`/hero-images/...`） |
| `recommended_video_ids` | JSON | - | おすすめ動画 ID 配列（保存順を表示順として使用） |
