# 開発環境セットアップ

## 前提条件

- Docker Desktop または Docker Engine + Docker Compose v2
- Git

## 手順

### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd minitube
```

### 2. 環境変数の設定

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

### 3. コンテナのビルドと起動

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

### 4. アクセス

ブラウザで `http://localhost` を開く。

- ホーム画面（視聴者向け）: `http://localhost/home`（未ログインでも公開動画を閲覧可）
- カテゴリ一覧: `http://localhost/categories`（未ログインでも閲覧可）
- 動画管理一覧: `http://localhost/videos`（テーブル形式。管理・編集用）
- ログインページ: `http://localhost/login`
- 新規登録ページ: `http://localhost/register`
- アップロードページ: `http://localhost/upload`（uploader または admin ロール必須）

### 5. MinIO コンソールの確認

MinIO の Web コンソールで保存されたファイルを確認できる:

```
http://localhost:9001
```

- ユーザ名: `.env` の `MINIO_ACCESS_KEY`（デフォルト: `minioadmin`）
- パスワード: `.env` の `MINIO_SECRET_KEY`

動画のアップロード・変換完了後、バケット（`minitube`）の `hls/` プレフィックス下にファイルが保存されているはず。

### 6. UI の使い方

**管理者 (admin@example.com) として:**
1. `http://localhost/login` でメールアドレスとパスワードを入力してログイン
2. 動画管理 `/videos` が表示される（ログイン後のリダイレクト先）
3. ホーム画面 `/home` では視聴者向けのタイル形式で動画一覧を閲覧できる
4. `/upload` でアップロードページへ（mp4 を選択し公開設定を選択してアップロード）
5. `/admin/users` でユーザ一覧と各ユーザのロール管理

**新規ユーザの登録:**
1. `/register` でメールアドレス・パスワードを入力して登録（自動的に `viewer` ロール付与）
2. `/login` でログイン
3. `viewer` ロールでは動画視聴のみ可能（アップロード不可）
4. 管理者が `/admin/users` から `uploader` ロールを付与すると動画アップロードが可能になる

**非公開動画の視聴権限付与:**
1. 非公開動画のプレイヤーページ（`/player/{id}`）を開く
2. 権限管理セクション（admin またはオーナーのみ表示）にメールアドレスを入力して「権限付与」
3. 付与したユーザはその動画をログイン後に視聴可能になる

### 7. コンテナの停止

```bash
docker compose down
```

データ（動画ファイル・DB・MinIO）を削除する場合:

```bash
docker compose down -v
```

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
