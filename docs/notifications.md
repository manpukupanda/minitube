# 通知機能（In-app Notifications）

## 概要

minitube では通知を `notifications` テーブルに保存し、ユーザごとに既読管理する。
通知はアプリ内のみで表示される（メール・Web Push は未対応）。

## 通知種別

- `new_video`: 新しい動画が追加された
- `video_updated`: 視聴済み動画が更新された（差し替え）
- `permission_granted`: 動画の閲覧権限が付与された
- `admin_message`: 管理者からのお知らせ

## 発火タイミング

- 動画追加（`POST /api/upload`）
  - 公開動画: 全ユーザへ通知
  - 非公開動画: オーナー・admin・権限付与済みユーザへ通知
- 動画差し替え（`POST /api/videos/{id}/replace`）
  - `watch_history` に記録があるユーザへ通知
- 閲覧権限付与（`POST /api/admin/videos/{id}/permissions`）
  - 対象ユーザへ通知
- 管理者通知送信（`POST /api/admin/notifications`）
  - 全ユーザまたは特定ロールへ通知

## API

- `GET /api/users/me/notifications`
  - 通知一覧を `created_at DESC` で返す
  - `?unread_only=true` で未読のみ取得
- `POST /api/notifications/{id}/read`
  - 単一通知を既読化（冪等）
- `POST /api/notifications/read_all`
  - 自分の未読通知を一括既読化
- `POST /api/admin/notifications`
  - 管理者が任意の通知を作成

## UI

- ヘッダーのベル（`/notifications` へのリンク）に未読件数を表示
- 通知一覧ページ（`/notifications`）
  - 通知タイトル / 本文 / 作成日時
  - 未読強調表示
  - 動画リンク（`video_id` がある場合）
  - 「すべて既読にする」操作

## 削除ポリシー

- ユーザによる通知削除は未対応（既読管理のみ）
- 自動削除は未対応
- 動画削除時は `notifications.video_id` を `ON DELETE SET NULL` で保持する
