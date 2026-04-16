# 後で見る（watch_later）

## 概要

後で見るは「今は見ないが後で見たい動画」を一時保存するための機能。  
お気に入り（長期保存）とは分離し、次の画面でのみ操作できる:

- プレイヤー画面: 追加・解除
- ホーム画面: 一覧表示・解除のみ

## データモデル

`watch_later` テーブル:

| カラム | 型 | 説明 |
|--------|-----|------|
| `user_id` | VARCHAR | FK → `users.id`（PK の一部） |
| `video_id` | VARCHAR | FK → `videos.id`（ON DELETE CASCADE、PK の一部） |
| `created_at` | BIGINT | 登録日時（UNIX タイムスタンプ） |
| `auto_removed_at` | BIGINT (NULL可) | 将来の自動削除用予約カラム |

主キーは `(user_id, video_id)` で、重複登録は不可。

## API

### POST `/api/videos/{id}/watch_later`

- 後で見る追加（ログイン必須）
- 既に登録済みでも 200（冪等）

### DELETE `/api/videos/{id}/watch_later`

- 後で見る解除（ログイン必須）
- 登録がなくても 200（冪等）

### GET `/api/users/me/watch_later`

- 自分の後で見る一覧を返す（ログイン必須）
- `created_at` 降順
- `auto_removed_at IS NULL` のみ対象

## UI

### プレイヤー画面

- タイトル横に後で見るトグルボタン（📍 / 📌）
- 初回ロード時に `/api/users/me/watch_later` で状態判定
- クリックで追加/解除 API を呼び出し

### ホーム画面

- 「後で見る（Watch Later）」セクションを表示（ログイン時）
- タイルごとに解除ボタン（📌）を配置
- 解除時は DELETE API を呼び出し、一覧から即時除去
- 追加操作は提供しない
