# minitube

最小構成の動画配信 Web アプリ。mp4 をアップロードすると HLS に変換し、RBAC によるロールベースのアクセス制御で動画の公開・非公開を管理できる。

---

## 主な機能

- **認証**: FastAPI の Cookie セッション（メールアドレス + bcrypt パスワード認証）
- **RBAC**: admin / uploader / viewer の 3 ロールによるアクセス制御
- **変換**: Worker コンテナが ffmpeg で mp4 → HLS（playlist.m3u8 + segment*.ts）に非同期変換
- **サムネイル**: HLS 変換後に ffmpeg でサムネイルを2種（固定秒・代表フレーム）自動生成し MinIO に保存。動画編集画面で切り替え可能
- **視聴履歴**: 再生開始・進捗・完了を自動記録。ホーム画面に「最近見た動画」「続きから再生」セクションを表示
- **お気に入り**: プレイヤー画面でお気に入り追加/解除、ホーム画面でお気に入り一覧表示と解除が可能
- **後で見る**: プレイヤー画面で後で見る追加/解除、ホーム画面で後で見る一覧表示と解除が可能
- **通知**: アプリ内通知（新着動画・更新動画・権限付与・管理者メッセージ）。ヘッダーのベルから確認し既読管理可能
- **ホーム画面運用設定**: admin が「お知らせ」「おすすめ動画」「ヒーローイメージ」を管理画面から更新可能
- **検索**: ホーム画面の検索バーから、タイトル・説明・タグ・カテゴリを横断検索
- **カテゴリ閲覧**: `/categories` でカテゴリ一覧（`/` 区切り名を階層表示）、`/categories/{category_id}` でカテゴリ別動画一覧を表示
- **キュー**: Redis Queue で API から Worker へ変換ジョブを受け渡す
- **保存**: Worker が変換後の HLS ファイルおよびサムネイルを **MinIO**（S3 互換オブジェクトストレージ）に永続保存
- **配信**: Nginx が secure_link_md5 検証後に **MinIO へ直接 proxy_pass**（proxy_cache 付き）。サムネイルも Nginx 経由で配信
- **保護**: 署名付きURL（1 時間有効）。公開動画は未ログインでも視聴可能。非公開動画は権限保有者のみ視聴可能

---

## セットアップ

### 前提条件

- Docker Desktop または Docker Engine + Docker Compose v2
- Git

### 手順

```bash
# 1. リポジトリのクローン
git clone <repository-url>
cd minitube

# 2. 環境変数の設定
cp .env.example .env
# .env を開いて SECRET_KEY・INITIAL_ADMIN_PASSWORD などを設定する

# 3. コンテナのビルドと起動
docker compose up --build
```

---

## 動作確認

ブラウザで `http://localhost` を開く（`/home` へリダイレクトされる）。

- ホーム画面: `http://localhost/home`（視聴者向け動画一覧。未ログインでも公開動画を閲覧可）
- カテゴリ一覧: `http://localhost/categories`（未ログインでも閲覧可）
- 検索結果: `http://localhost/search?q=キーワード`（未ログインでも公開動画を閲覧可）
- 動画管理: `http://localhost/videos`（テーブル形式。管理・編集用）
- ログイン: `http://localhost/login`（初期管理者: `admin@example.com`）
- アップロード: `http://localhost/upload`（uploader または admin ロール必須）
- MinIO コンソール: `http://localhost:9001`

---

## ドキュメント

詳細な仕様・設定については `docs/` 以下を参照。

| ドキュメント | 内容 |
|------------|------|
| [docs/architecture.md](docs/architecture.md) | コンテナ構成図・ディレクトリ構成・API 一覧・DB スキーマ |
| [docs/auth.md](docs/auth.md) | 認証フロー・Cookie セッション |
| [docs/rbac.md](docs/rbac.md) | RBAC・ロール仕様・VideoPermission |
| [docs/profile.md](docs/profile.md) | プロフィール編集・アイコン・パスワード変更 |
| [docs/thumbnails.md](docs/thumbnails.md) | サムネイル自動生成・種別・切り替え |
| [docs/watch_history.md](docs/watch_history.md) | 視聴履歴・続きから再生・履歴 API |
| [docs/favorites.md](docs/favorites.md) | お気に入り機能・お気に入り API |
| [docs/watch_later.md](docs/watch_later.md) | 後で見る機能・後で見る API |
| [docs/notifications.md](docs/notifications.md) | 通知機能・通知 API・通知発火条件 |
| [docs/worker.md](docs/worker.md) | HLS 変換・Worker 処理フロー・Redis Queue |
| [docs/nginx.md](docs/nginx.md) | Nginx secure_link・proxy_cache・キャッシュ削除 |
| [docs/storage.md](docs/storage.md) | MinIO オブジェクト構造・HLS ディレクトリ例 |
| [docs/development.md](docs/development.md) | 開発環境セットアップ・トラブルシューティング |
| [docs/deployment.md](docs/deployment.md) | 本番デプロイ手順 |
| [docs/techstack.md](docs/techstack.md) | 技術スタック一覧 |

---

## ライセンス

MIT
