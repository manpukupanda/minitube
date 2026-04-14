# MinIO オブジェクト構造

## オブジェクトキー規約

HLS ファイルは以下のキーで MinIO バケット（デフォルト: `minitube`）に保存される:

```
hls/{video_id}/playlist.m3u8
hls/{video_id}/segment000.ts
hls/{video_id}/segment001.ts
...
```

サムネイル画像は以下のキーで保存される:

```
videos/{video_id}/thumbnails/{thumbnail_id}.jpg
```

アイコン画像は以下のキーで保存される:

```
user-icons/{user_id}.png   ← PNG の場合
user-icons/{user_id}.jpg   ← JPEG の場合
```

## Nginx URI から MinIO パスへの対応

| Nginx リクエスト URI | MinIO オブジェクトキー |
|---------------------|----------------------|
| `/videos/{id}/segment000.ts` | `hls/{id}/segment000.ts` |
| `/videos/{id}/segment001.ts` | `hls/{id}/segment001.ts` |
| `/thumbnails/{id}/{thumbnail_id}.jpg` | `videos/{id}/thumbnails/{thumbnail_id}.jpg` |
| `/user-icons/{user_id}.{ext}` | `user-icons/{user_id}.{ext}` |

## HLS ディレクトリ構造例

MinIO バケット（`minitube`）内のオブジェクト:

```
hls/
└── a1b2c3d4e5f/                          ← 動画 ID（Base62 11文字）
    ├── playlist.m3u8                      ← HLS プレイリスト
    ├── segment000.ts                      ← セグメント 0（0〜4 秒）
    ├── segment001.ts                      ← セグメント 1（4〜8 秒）
    ├── segment002.ts                      ← セグメント 2（8〜12 秒）
    └── ...
videos/
└── a1b2c3d4e5f/                          ← 動画 ID（Base62 11文字）
    └── thumbnails/
        ├── b2c3d4e5f6g.jpg               ← 固定秒サムネイル（active=true）
        └── c3d4e5f6g7h.jpg               ← 代表フレームサムネイル（active=false）
user-icons/
└── {user_id}.{ext}                       ← ユーザアイコン
```

ローカルの `/videos` ボリュームには `input.mp4` のみ一時的に保存され、変換後に削除される。

## playlist.m3u8 の中身（例）

```
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:4.000000,
segment000.ts
#EXTINF:4.000000,
segment001.ts
#EXTINF:3.800000,
segment002.ts
#EXT-X-ENDLIST
```

FastAPI の `/api/videos/{id}/playlist` が上記を MinIO から読み込み、各セグメント行を署名付き URI に書き換えて返す:

```
#EXTINF:4.000000,
/videos/{id}/segment000.ts?expires=1712345678&md5=abc123XYZ...
```
