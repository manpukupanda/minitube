# お気に入り（favorites）

## 概要

お気に入りは「長期保存したい動画」を管理するための機能。  
ブックマーク（後で見る）とは分離し、次の画面でのみ操作できる:

- プレイヤー画面: 追加・解除
- ホーム画面: 一覧表示・解除のみ

## データモデル

`favorites` テーブル:

| カラム | 型 | 説明 |
|--------|-----|------|
| `user_id` | VARCHAR | FK → `users.id`（PK の一部） |
| `video_id` | VARCHAR | FK → `videos.id`（ON DELETE CASCADE、PK の一部） |
| `created_at` | BIGINT | 登録日時（UNIX タイムスタンプ） |

主キーは `(user_id, video_id)` で、重複登録は不可。

## API

### POST `/api/videos/{id}/favorite`

- お気に入り追加（ログイン必須）
- 既に登録済みでも 200（冪等）

### DELETE `/api/videos/{id}/favorite`

- お気に入り解除（ログイン必須）
- 登録がなくても 200（冪等）

### GET `/api/users/me/favorites`

- 自分のお気に入り一覧を返す（ログイン必須）
- `created_at` 降順

## UI

### プレイヤー画面

- タイトル横にお気に入りトグルボタン（★ / ☆）
- 初回ロード時に `/api/users/me/favorites` で状態判定
- クリックで追加/解除 API を呼び出し

### ホーム画面

- 「お気に入り」セクションを表示（ログイン時）
- タイルごとに解除ボタン（★）を配置
- 解除時は DELETE API を呼び出し、一覧から即時除去
- 追加操作は提供しない
