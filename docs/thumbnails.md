# サムネイル自動生成

動画アップロード後の HLS 変換が完了すると、Worker が自動でサムネイルを2種類生成し MinIO に保存する。

## サムネイル種別

| 種別 | `type` | 生成方法 | `active` |
|------|--------|---------|---------|
| 固定秒サムネイル | `fixed` | `duration >= 5` → 5秒地点、`< 5` → `duration/2` | `true`（デフォルト） |
| 代表フレームサムネイル | `representative` | ffmpeg `thumbnail` フィルタ（シーン的に代表的なフレーム） | `false` |

## active フラグ

- `active=true` のサムネイルが動画一覧（`/videos`）のサムネイル列に表示される
- 常に1件のみ `active=true` となる
- 動画編集画面から切り替え可能

## ffmpeg コマンド例

```bash
# 固定秒サムネイル（5秒地点）
ffmpeg -ss 5 -i input.mp4 -vframes 1 -vf "scale=480:-1" thumb_fixed.jpg

# 代表フレームサムネイル
ffmpeg -i input.mp4 -vf "thumbnail,scale=480:-1" -frames:v 1 thumb_rep.jpg
```

## 動画編集画面での切り替え

- `/videos/{id}/edit` にサムネイルグリッドが表示される
- 「このサムネイルを使う」ボタンをクリックすると `POST /api/videos/{id}/thumbnails/{thumb_id}/activate` が呼ばれ active が切り替わる
- 動画一覧（`/videos`）では active なサムネイルがサムネイル列に表示される
