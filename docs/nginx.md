# Nginx secure_link / proxy_cache

## secure_link の仕組みと署名仕様

### 署名仕様（Nginx secure_link_md5 と同一）

```
secure_link_md5 "$secure_link_expires${uri}${SECRET_KEY}";
```

FastAPI と Nginx は同じ計算式で署名を生成・検証する:

| 要素 | 説明 |
|------|------|
| `expires` | UNIX タイムスタンプ（現在時刻 + 3600 秒） |
| `uri` | クエリを含まないパス（例: `/videos/abc/segment000.ts`） |
| `SECRET_KEY` | 環境変数から注入（コミット禁止） |

```
raw_string = expires + uri + SECRET_KEY
signature  = base64url_nopad( MD5( raw_string.encode('utf-8') ) )
```

### 署名フロー図

```
FastAPI（署名生成）                    Nginx（署名検証）
─────────────────────                  ─────────────────────
expires = 現在時刻 + 3600              受信: ?expires=TS&md5=SIG

raw = expires + uri + SECRET_KEY       raw = $secure_link_expires
    = "1712345678"                          + $uri
      + "/videos/abc/segment000.ts"         + SECRET_KEY（envsubstで埋め込み済）
      + "mysecret"

MD5(raw) をバイナリ計算               MD5(raw) を同様に計算
Base64url エンコード（パディングなし） Base64url エンコード

sig = "abc123XYZ..."                   計算値 == $arg_md5 → MinIO へ proxy
                                       計算値 != $arg_md5 → 403 Forbidden
URL = /videos/abc/segment000.ts        expires < 現在時刻  → 403 Forbidden
    + ?expires=1712345678
    + &md5=abc123XYZ...
```

---

## Nginx proxy_cache の意図と注意点

### キャッシュの目的

Nginx は secure_link 検証後に MinIO へ proxy_pass し、レスポンスをローカルキャッシュに保存する。
同一セグメントへの繰り返しアクセスは MinIO への upstream リクエストを省略できる。

### キャッシュキー方針（重要）

```nginx
proxy_cache_key "$uri";
```

**`$uri`（パスのみ）をキャッシュキーとし、クエリパラメータ（`expires`/`md5`）をキャッシュキーから除外**している。
これにより有効期限や署名値が変わっても、同一セグメントファイルは同一キャッシュエントリにヒットする。

**安全性の根拠**:
- `expires`/`md5` の検証は secure_link が担当し、403 は proxy_cache に到達する前に返される
- キャッシュに到達するのは検証通過済みリクエストのみ
- キャッシュキーからクエリを除外しても、不正なリクエストがキャッシュヒットすることはない

**`$uri` をキャッシュキーにする理由**:
- Worker/API が同じロジックでキャッシュファイルパスを逆算でき、動画差し替え時に古いキャッシュを削除できる

### キャッシュ状態の確認

レスポンスの `X-Cache-Status` ヘッダでキャッシュ状態を確認できる:

| 値 | 意味 |
|----|------|
| `MISS` | キャッシュなし（MinIO から取得） |
| `HIT` | キャッシュヒット（MinIO へのアクセスなし） |
| `EXPIRED` | キャッシュ期限切れ（MinIO から再取得） |

```bash
# キャッシュ確認例
curl -v "http://localhost/videos/{id}/segment000.ts?expires=...&md5=..." 2>&1 | grep X-Cache-Status
```

---

## Nginx キャッシュ削除の仕組み

### 背景と課題

Nginx の `proxy_cache` はキャッシュファイルをローカルのファイルシステムに保存する。
動画を差し替えて MinIO の HLS を更新しても、Nginx のキャッシュが残っていると古い動画が配信され続ける。
Nginx 標準機能では特定キャッシュのみを削除する手段がないが、
**キャッシュキー → MD5 → ファイルパス** を逆算すれば削除可能。

### キャッシュファイルパスの逆算

Nginx の `proxy_cache_path levels=1:2` と `proxy_cache_key "$uri"` の組み合わせにより、
キャッシュファイルのパスは以下のロジックで一意に決定される:

```python
import hashlib, os

uri = "/videos/{video_id}/segment000.ts"  # キャッシュキー（$uri と同一）
md5 = hashlib.md5(uri.encode()).hexdigest()  # 例: "1a3f9c8d7b2e4f6a0c5d8e1f3a7b9c2d"

# levels=1:2 によるディレクトリ構造
cache_path = os.path.join(
    "/tmp/nginx/hls_cache",
    md5[-1],       # 1 文字目のサブディレクトリ（例: "d"）
    md5[-3:-1],    # 2 文字目のサブディレクトリ（例: "2c"）
    md5,           # ファイル名（フルハッシュ）
)
# → /tmp/nginx/hls_cache/d/2c/1a3f9c8d7b2e4f6a0c5d8e1f3a7b9c2d
```

### ボリューム共有による削除

Nginx キャッシュディレクトリ（`/tmp/nginx/hls_cache`）を Docker の名前付きボリューム（`nginx_cache`）として
nginx / worker / api の 3 コンテナで共有する。これにより各コンテナからキャッシュファイルを直接削除できる。

```yaml
volumes:
  nginx_cache:   # nginx / worker / api コンテナで共有
```

### 動画差し替え時の自動削除（Worker）

`worker/jobs/split.py` の `run_split()` は、MinIO への HLS アップロード成功後に
`worker/utils/nginx_cache.py` の `delete_nginx_cache_for_video()` を呼び出して
古い Nginx キャッシュを自動的に削除する。

### UI によるキャッシュ手動削除（API）

動画編集ページ（`/videos/{video_id}/edit`）に「キャッシュを削除する」ボタンを設置した。
ボタンをクリックすると `POST /api/videos/{video_id}/clear_cache` が呼ばれ、
MinIO から HLS ファイル一覧を取得して対応する Nginx キャッシュを削除する。

```
API フロー:
  POST /api/videos/{id}/clear_cache
    → MinIO から hls/{id}/ 以下のオブジェクト一覧を取得
    → 各 URI に対してキャッシュパスを計算して削除
    → /videos/{id}/edit?cache_cleared={N} へリダイレクト
```

### 環境変数

| 変数 | デフォルト値 | 説明 |
|------|------------|------|
| `NGINX_CACHE_DIR` | `/tmp/nginx/hls_cache` | Nginx キャッシュディレクトリのパス |

### Nginx 設定確認

```bash
# Nginx コンテナに入って設定を確認
docker compose exec nginx nginx -t
docker compose exec nginx cat /etc/nginx/nginx.conf

# Nginx のアクセスログでキャッシュ状態を確認
docker compose logs nginx --tail=50
```

## 画像配信（サムネイル / アイコン / ヒーロー画像）

Nginx は以下の画像 URL を MinIO へ proxy_pass して配信する（ブラウザは MinIO を直接参照しない）。

- `/thumbnails/{video_id}/{thumbnail_id}.jpg` → `/${MINIO_BUCKET}/videos/{video_id}/thumbnails/{thumbnail_id}.jpg`
- `/user-icons/{user_id}.{ext}` → `/${MINIO_BUCKET}/user-icons/{user_id}.{ext}`
- `/hero-images/{id}.{ext}` → `/${MINIO_BUCKET}/hero-images/{id}.{ext}`
