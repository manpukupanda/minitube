# HLS 変換・Worker 処理

## 概要

Worker コンテナは Redis Queue を監視し、mp4 → HLS 変換・サムネイル生成・MinIO アップロードを非同期で実行する。

## mp4 → HLS 変換

Worker が ffmpeg を使って mp4 を HLS（`playlist.m3u8` + `segment*.ts`）に変換する。

```
ffmpeg -i input.mp4 -c:v libx264 -c:a aac \
  -hls_time 4 -hls_list_size 0 \
  -hls_segment_filename "segment%03d.ts" \
  playlist.m3u8
```

変換後、HLS ファイルは MinIO の `hls/{video_id}/` プレフィックスに保存される。

## Redis Queue

- API が変換ジョブを Redis Queue（`split_jobs` キュー）に `RPUSH` する
- Worker が `BLPOP` でジョブを取り出して処理する
- ジョブ状態は PostgreSQL の `jobs` テーブルで管理される（`queued` / `processing` / `completed` / `error`）

## MinIO アップロード

Worker は boto3 を使って以下のファイルを MinIO にアップロードする:

- `hls/{video_id}/playlist.m3u8`
- `hls/{video_id}/segment000.ts`, `segment001.ts`, ...
- `videos/{video_id}/thumbnails/{thumbnail_id}.jpg`（サムネイル）

## Nginx キャッシュ削除

動画差し替え時、Worker は新しい HLS を MinIO にアップロードした後、
`worker/utils/nginx_cache.py` の `delete_nginx_cache_for_video()` を呼び出して古い Nginx キャッシュを自動的に削除する。
詳細は [docs/nginx.md](nginx.md) を参照。

## Worker の処理フロー

```
動画アップロード → 変換フロー:
  1. API: input.mp4 を /videos ボリュームに保存
  2. API: videos レコードを作成（status = "processing"）
  3. API: split ジョブを Redis Queue に enqueue（jobs.status = "queued"）
  4. API: 動画編集画面 /videos/{video_id}/edit へリダイレクト
  5. Worker: BLPOP でジョブを取り出す（jobs.status = "processing"）
  6. Worker: ffmpeg で mp4 → HLS 変換
  7. Worker: ffmpeg でサムネイル生成（fixed + representative）
  8. Worker: HLS ファイルを MinIO にアップロード
  9. Worker: サムネイルを MinIO にアップロード
  10. Worker: thumbnails テーブルに2件レコードを INSERT（fixed が active=true）
  11. Worker: Nginx キャッシュを削除
  12. Worker: jobs.status = "completed"、videos.status = "ready" に UPDATE

動画差し替えフロー:
  1. API: 古い HLS を MinIO から削除
  2. API: 新しい input.mp4 を /videos ボリュームに保存
  3. API: split ジョブを Redis Queue に enqueue
  4. Worker: ffmpeg で mp4 → HLS 変換
  5. Worker: 新しい HLS を MinIO にアップロード
  6. Worker: Nginx キャッシュを削除
  7. Worker: DB のジョブ状態を completed に更新
```

## 動画ステータスの遷移

```
アップロード → processing → ready（変換成功）
                           → failed（変換失敗）
差し替え     → processing → ready / failed
```

## トラブルシューティング

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
