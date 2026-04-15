# 視聴履歴（watch_history）

## 概要

minitube の視聴履歴機能は、ユーザが視聴した動画の進捗を記録し、  
ホーム画面の「最近見た動画」「続きから再生」セクションに活用する。

---

## データモデル

### watch_history テーブル

| カラム | 型 | NULL 許可 | 説明 |
|--------|-----|----------|------|
| `user_id` | VARCHAR | - | FK → users.id（PK の一部） |
| `video_id` | VARCHAR | - | FK → videos.id（ON DELETE CASCADE、PK の一部） |
| `last_watched_at` | BIGINT | - | 最後に視聴した日時（UNIX タイムスタンプ） |
| `last_position` | INTEGER | - | 最後に視聴した再生位置（秒）、デフォルト 0 |
| `duration` | INTEGER | 許可 | 動画の長さ（秒）、初回 progress 時に保存 |
| `completed` | BOOLEAN | - | 視聴完了フラグ、デフォルト false |

- **主キー**: `(user_id, video_id)` → 1 ユーザにつき 1 動画の履歴が 1 行にまとまる
- **動画削除時**: `ON DELETE CASCADE` で履歴も自動削除される
- **インデックス**: `user_id`、`last_watched_at`

---

## API エンドポイント

### POST /api/videos/{id}/watch

再生開始時に呼び出す。履歴がなければ作成、あれば `last_watched_at` を更新する。

- **認証**: 必須（未ログインは 401）
- **リクエストボディ**: なし
- **レスポンス**: `{"ok": true}`

### POST /api/videos/{id}/progress

再生位置と動画長を更新する（10〜30 秒間隔で呼び出すことを想定）。

- **認証**: 必須（未ログインは 401）
- **リクエストボディ**: JSON `{"position": <秒>, "duration": <秒>}`
  - `duration` は省略可。初回のみ保存される
- **レスポンス**: `{"ok": true}`

### POST /api/videos/{id}/complete

視聴完了時に呼び出す。`completed = true` に更新する。

- **認証**: 必須（未ログインは 401）
- **リクエストボディ**: なし
- **レスポンス**: `{"ok": true}`

### GET /api/users/me/history

最近見た動画一覧を返す（`last_watched_at` の降順）。

- **認証**: 必須（未ログインは 401）
- **レスポンス**:
  ```json
  {
    "history": [
      {
        "video_id": "abc12345678",
        "title": "サンプル動画",
        "last_watched_at": 1713000000,
        "last_position": 120,
        "duration": 600,
        "completed": false
      }
    ]
  }
  ```

### GET /api/users/me/resume

続きから再生できる動画一覧を返す（`last_position > 0`、`last_watched_at` の降順）。

- **認証**: 必須（未ログインは 401）
- **レスポンス**: `{"resume": [...]}` （上記と同じ構造）

---

## hls.js イベント処理

`player.html` の JavaScript で以下のタイミングに呼び出す。

| イベント | 呼び出し API | 説明 |
|---------|------------|------|
| `Hls.Events.MANIFEST_PARSED` / `loadedmetadata` | `/api/videos/{id}/watch` | 再生開始を記録 |
| `setInterval`（15 秒間隔） | `/api/videos/{id}/progress` | 再生位置を定期更新 |
| `ended` | `/api/videos/{id}/complete` | 視聴完了を記録 |

---

## ホーム画面

ログイン済みユーザに対して、ホーム画面に以下のセクションを表示する。

| セクション | 表示条件 | 並び順 |
|-----------|---------|-------|
| 続きから再生 | `last_position > 0` の履歴がある | `last_watched_at` 降順 |
| 最近見た動画 | 視聴履歴がある | `last_watched_at` 降順（最大 10 件） |

---

## 削除方針

ユーザによる履歴削除機能は実装しない。  
理由: minitube は会員制 + 業務用途を想定しており、履歴は学習進捗データとして扱う。

- 動画削除時は `ON DELETE CASCADE` で履歴も自動削除される
- 管理者による履歴削除 API は将来の拡張として別 Issue で扱う
