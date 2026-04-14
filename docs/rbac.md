# RBAC・ユーザ管理

## ロール

| ロール | 説明 |
|--------|------|
| `admin` | 全機能にアクセス可能。ユーザ管理・全動画管理 |
| `uploader` | 動画のアップロードが可能 |
| `viewer` | 動画の視聴のみ可能（新規登録ユーザはこのロール） |

## 動画の公開設定

| 設定 | 説明 |
|------|------|
| `public` | 未ログインを含む全員が視聴可能 |
| `private` | admin・オーナー・権限付与されたユーザのみ視聴可能 |

## 初期管理者ユーザ

起動時に `admin@example.com` ユーザが自動作成される（`INITIAL_ADMIN_PASSWORD` 環境変数で設定）。
パスワードは初回起動時のみ設定され、再起動時には更新されない（冪等性）。

## VideoPermission（動画視聴権限）

非公開動画に対して、admin またはオーナーが特定ユーザに視聴権限を付与できる。
プレイヤーページ（`/player/{id}`）の権限管理セクションから操作可能。

## 権限付与フロー

1. 非公開動画のプレイヤーページ（`/player/{id}`）を開く
2. 権限管理セクション（admin またはオーナーのみ表示）にメールアドレスを入力して「権限付与」
3. 付与したユーザはその動画をログイン後に視聴可能になる

## ロール管理 API

| メソッド | パス | 説明 | 認証 |
|---------|------|------|------|
| GET | `/admin/users` | Admin 専用ユーザ管理ページ | 必要（admin） |
| POST | `/api/admin/users/{id}/roles` | ロール付与 | 必要（admin） |
| POST | `/api/admin/users/{id}/roles/{role}/delete` | ロール削除 | 必要（admin） |
| POST | `/api/admin/videos/{id}/permissions` | 動画視聴権限付与 | 必要（admin/オーナー） |
| POST | `/api/admin/videos/{id}/permissions/{uid}/delete` | 動画視聴権限削除 | 必要（admin/オーナー） |
