"""
minitube - 最小構成の動画配信 Web アプリ（FastAPI バックエンド）

このモジュールは以下の機能を提供する:

1. 認証（Cookie ベースのセッション管理）
   - /login          : ログインページ（HTML）
   - /api/login      : ログイン処理（POST）
   - /logout         : ログアウト処理

2. 動画アップロード
   - /upload         : アップロードページ（HTML）
   - /api/upload     : アップロード処理（POST）
     mp4 を受け取り、/videos/{id}/input.mp4 に保存して Redis Queue に enqueue する

3. 動画プレイヤー
   - /player/{id}    : プレイヤーページ（HTML）

4. 署名付きURL生成（secure_link_md5）
   - /api/videos/{id}/url : 署名付き HLS プレイリスト URL を返す
     Nginx の secure_link_md5 と互換性のある md5 署名を付与する

5. ジョブ状態取得
   - /api/job/{job_id} : ジョブ状態を返す（queued/processing/completed/error）

技術的なポイント:
   - 認証は FastAPI の Cookie セッション（itsdangerous で署名）で完結する
   - Nginx は認証を行わず、HLS ファイルの署名検証のみを担当する
   - SECRET_KEY は環境変数から取得し、コードには直書きしない
   - データベースは PostgreSQL を使用し、SQLAlchemy ORM 経由でアクセスする
   - マイグレーションは Alembic で管理し、起動時に自動適用する
   - HLS 変換は Worker コンテナが非同期で実行する（Redis Queue 経由）
"""

import base64
import hashlib
import os
import secrets
import shutil
import time
import uuid

import boto3
import redis as redis_lib
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import BigInteger, Column, String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from starlette.middleware.sessions import SessionMiddleware


# ==============================================================
# アプリケーション初期化
# ==============================================================

app = FastAPI(title="minitube", description="最小構成の動画配信 Web アプリ")

# セッションミドルウェアを追加する
# itsdangerous を使って Cookie を署名付きで管理するため、
# SECRET_KEY と同じ値を使用することで管理を一元化する
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "changeme_replace_in_production"),
    # HttpOnly = True はデフォルトで有効
    # SameSite = Lax（CSRF 対策として有効）
    same_site="lax",
    # Secure = False（ローカル開発環境のため）
    https_only=False,
)

# Jinja2 テンプレートエンジンを設定する
# templates/ ディレクトリに HTML ファイルを配置する
templates = Jinja2Templates(directory="templates")

# HLS ファイルの出力先ディレクトリ
# docker-compose の volumes で Nginx と共有する
VIDEOS_DIR = "/videos"

# Redis キュー名（split ジョブ用）
SPLIT_QUEUE = "split_jobs"


# ==============================================================
# データベース設定（SQLAlchemy + PostgreSQL）
# ==============================================================

# DATABASE_URL は環境変数から取得する
# 形式: postgresql://<user>:<password>@<host>/<dbname>
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://minitube:changeme_replace_in_production@db/minitube",
)

# pool_pre_ping=True を設定することで、コネクション取得時に生死確認を行い、
# 切断済みコネクションを自動的に再接続する（DB 起動直後の接続失敗対策）
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Video(Base):
    """動画メタ情報を保持する ORM モデル。"""

    __tablename__ = "videos"

    # 動画の一意識別子（UUID v4 の文字列表現）
    id = Column(String, primary_key=True)
    # 元のファイル名（表示用タイトル）
    title = Column(String, nullable=False)
    # 登録日時（UNIX タイムスタンプ、秒単位）
    # テンプレートの JS が `ts * 1000` で Date に変換するため BIGINT を使用する
    created_at = Column(BigInteger, nullable=False)


class Job(Base):
    """動画処理ジョブの状態を管理する ORM モデル。"""

    __tablename__ = "jobs"

    # ジョブの一意識別子（UUID v4 の文字列表現）
    id = Column(String, primary_key=True)
    # 対象動画の UUID
    video_id = Column(String, nullable=False)
    # ジョブ種別（現在は 'split' のみ）
    type = Column(String, nullable=False)
    # ジョブ状態: queued | processing | completed | error
    status = Column(String, nullable=False, default="queued")
    # エラー時のメッセージ（nullable）
    error_message = Column(String, nullable=True)
    # 作成日時（UNIX タイムスタンプ、秒単位）
    created_at = Column(BigInteger, nullable=False)
    # 更新日時（UNIX タイムスタンプ、秒単位）
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("video_id", "type", name="uq_jobs_video_id_type"),
    )


def get_db():
    """
    FastAPI の依存性注入で使用するデータベースセッションジェネレータ。

    各リクエストに対して独立したセッションを生成し、
    レスポンス返却後（または例外発生後）に必ずセッションをクローズする。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==============================================================
# Redis クライアント設定
# ==============================================================

# REDIS_URL は環境変数から取得する（デフォルト: redis://redis:6379/0）
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
redis_client = redis_lib.from_url(REDIS_URL)


# ==============================================================
# MinIO クライアント設定
# ==============================================================

def _get_s3_client():
    """
    MinIO への boto3 S3 クライアントを返す。

    環境変数から接続情報を取得する:
        MINIO_ENDPOINT   : MinIO の S3 API エンドポイント（例: http://minio:9000）
        MINIO_ACCESS_KEY : MinIO の root アクセスキー
        MINIO_SECRET_KEY : MinIO の root シークレットキー
    """
    endpoint = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
    access_key = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.environ.get("MINIO_SECRET_KEY", "changeme_minio_secret")

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        # MinIO はリージョンを気にしないが boto3 は必須のため設定する
        region_name="us-east-1",
    )


# ==============================================================
# 認証ユーティリティ
# ==============================================================

class NotAuthenticated(Exception):
    """未認証ユーザがアクセスしたときに発生させる例外。"""
    pass


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, exc: NotAuthenticated):
    """
    NotAuthenticated 例外を受け取り、ログインページにリダイレクトする。

    HTML ページへのアクセスが前提のため、JSON エラーではなく
    303 See Other でリダイレクトする。
    """
    return RedirectResponse(url="/login", status_code=303)


def require_login(request: Request) -> str:
    """
    ログイン済みユーザのみがアクセスできるエンドポイント用の依存関数。

    セッションに "user" キーが存在しない場合は NotAuthenticated を送出する。
    各ルート関数で `user: str = Depends(require_login)` のように使用する。

    Returns:
        str: セッションに保存されたユーザ名（"admin"）
    Raises:
        NotAuthenticated: 未認証の場合
    """
    user = request.session.get("user")
    if not user:
        raise NotAuthenticated()
    return user


# ==============================================================
# 署名付きURL生成ユーティリティ
# ==============================================================

def generate_signed_url(video_id: str) -> str:
    """
    Nginx の secure_link_md5 と互換性のある署名付きURLを生成する。

    署名の計算式:
        raw_string = expires + uri + secret_key
        signature  = base64url( MD5( raw_string.encode('utf-8') ) )
        url        = /videos/{id}/playlist.m3u8?expires={expires}&md5={signature}

    例:
        expires    = 1712345678
        uri        = /videos/abc123/playlist.m3u8
        secret_key = mysecret
        raw_string = "1712345678/videos/abc123/playlist.m3u8mysecret"
        signature  = base64url( MD5("1712345678/videos/abc123/playlist.m3u8mysecret") )

    Nginx 側の設定（nginx.conf）:
        secure_link $arg_md5,$arg_expires;
        secure_link_md5 "$secure_link_expires$uri${SECRET_KEY}";

    注意:
        - base64 は URL セーフ形式（+ → -、/ → _）でパディング（=）なし
        - Nginx が同じ文字列に対して同じ MD5 を計算するため一致する

    Args:
        video_id: 動画の UUID

    Returns:
        str: 署名付き HLS プレイリスト URL（/videos/...?expires=...&md5=...）
    """
    secret_key = os.environ.get("SECRET_KEY", "changeme_replace_in_production")

    # 有効期限を現在時刻 + 3600 秒（1 時間）に設定する
    expires = int(time.time()) + 3600

    # 署名対象の URI（クエリパラメータなしのパス）
    uri = f"/videos/{video_id}/playlist.m3u8"

    # Nginx の secure_link_md5 と同じ文字列を組み立てる
    # 形式: expires + uri + secret_key（スペースなしで結合）
    raw_string = f"{expires}{uri}{secret_key}"

    # MD5 ダイジェストを計算し、URL セーフ base64 でエンコードする
    # Nginx は base64url エンコード（パディングなし）を期待する
    # 注意: MD5 は Nginx の secure_link_md5 モジュールとの相互運用性のために必須。
    # パスワードハッシュや機密データの保護には使用していない（プロトコル要件）。
    digest = hashlib.md5(raw_string.encode("utf-8")).digest()  # noqa: S324
    signature = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")

    return f"{uri}?expires={expires}&md5={signature}"


# ==============================================================
# ルート定義
# ==============================================================

# --------------------------------------------------------------
# ルートリダイレクト
# --------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root():
    """
    ルートパスへのアクセスをアップロードページにリダイレクトする。
    未認証の場合は require_login により /login にリダイレクトされる。
    """
    return RedirectResponse(url="/upload", status_code=302)


# --------------------------------------------------------------
# 認証エンドポイント
# --------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    """
    ログインページを返す。

    認証済みの場合はアップロードページにリダイレクトする。

    Args:
        request: FastAPI リクエストオブジェクト
        error:   エラーフラグ（"1" の場合はエラーメッセージを表示する）
    """
    # すでにログイン済みならアップロードページにリダイレクト
    if request.session.get("user"):
        return RedirectResponse(url="/upload", status_code=303)

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": error == "1",
        },
    )

@app.post("/api/login")
async def api_login(
    request: Request,
    password: str = Form(...),
):
    """
    ログイン処理を行い、認証 Cookie を発行する。

    パスワードは環境変数 ADMIN_PASSWORD から取得する（デフォルト: admin）。
    認証成功時はセッションに "user" キーを設定し、アップロードページにリダイレクト。
    認証失敗時は /login?error=1 にリダイレクト。

    セキュリティ上の注意:
        - 本番環境では ADMIN_PASSWORD を強固なものに変更すること
        - レートリミットや試行回数制限は本実装には含まれない（最小構成のため）

    Args:
        request:  FastAPI リクエストオブジェクト
        password: フォームから送信されたパスワード
    """
    # 環境変数からパスワードを取得する（デフォルトは "admin"）
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin")

    if secrets.compare_digest(password, admin_password):
        # 認証成功: セッションにユーザ名を保存する
        request.session["user"] = "admin"
        return RedirectResponse(url="/upload", status_code=303)
    else:
        # 認証失敗: エラーフラグ付きでログインページにリダイレクト
        return RedirectResponse(url="/login?error=1", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    """
    ログアウト処理を行い、セッションをクリアしてログインページにリダイレクトする。
    """
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# --------------------------------------------------------------
# アップロードエンドポイント
# --------------------------------------------------------------

@app.get("/upload", response_class=HTMLResponse)
async def upload_page(
    request: Request,
    _user: str = Depends(require_login),
    db: Session = Depends(get_db),
):
    """
    動画アップロードページを返す。未認証の場合は /login にリダイレクト。

    各動画の split ジョブ状態も合わせて返す。

    Args:
        request: FastAPI リクエストオブジェクト
        _user:   ログイン確認用依存関数（戻り値は使用しない）
        db:      データベースセッション
    """
    # アップロード済み動画一覧を取得して表示する
    videos = (
        db.query(Video)
        .order_by(Video.created_at.desc())
        .all()
    )

    # 各動画の split ジョブ状態を取得する
    video_ids = [v.id for v in videos]
    jobs = (
        db.query(Job)
        .filter(Job.video_id.in_(video_ids), Job.type == "split")
        .all()
    ) if video_ids else []
    job_map = {j.video_id: j for j in jobs}

    video_list = []
    for v in videos:
        job = job_map.get(v.id)
        # ジョブが存在しない場合（移行前の既存動画）は completed として扱う
        status = job.status if job else "completed"
        job_id = job.id if job else None
        video_list.append({
            "id": v.id,
            "title": v.title,
            "created_at": v.created_at,
            "status": status,
            "job_id": job_id,
        })

    return templates.TemplateResponse(
        request,
        "upload.html",
        {
            "videos": video_list,
        },
    )


@app.post("/api/upload")
async def api_upload(
    request: Request,
    file: UploadFile = File(...),
    _user: str = Depends(require_login),
    db: Session = Depends(get_db),
):
    """
    mp4 ファイルをアップロードし、Redis Queue に split ジョブを登録する。

    処理の流れ:
        1. アップロードされた mp4 を /videos/{uuid}/input.mp4 に保存
        2. PostgreSQL に動画メタ情報（id, title, created_at）を保存
        3. jobs テーブルに split ジョブを INSERT（status = queued）
        4. Redis Queue に job_id を enqueue
        5. /player/{uuid} にリダイレクト

    Worker が /videos/{uuid}/input.mp4 を読み込んで HLS 変換を行う。

    Args:
        request: FastAPI リクエストオブジェクト
        file:    アップロードされた mp4 ファイル
        _user:   ログイン確認用依存関数
        db:      データベースセッション

    Returns:
        RedirectResponse: /player/{video_id} へのリダイレクト
    """
    # 動画の一意識別子を生成する（UUID v4）
    video_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    now = int(time.time())

    # HLS 出力先ディレクトリを作成する
    output_dir = os.path.join(VIDEOS_DIR, video_id)
    os.makedirs(output_dir, exist_ok=True)

    # アップロードされた mp4 を共有ボリュームに保存する
    # Worker がこのファイルを読み込んで HLS 変換を実行する
    input_path = os.path.join(output_dir, "input.mp4")
    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # PostgreSQL に動画メタ情報を保存する
    video = Video(
        id=video_id,
        title=file.filename or "無題",
        created_at=now,
    )
    db.add(video)

    # jobs テーブルに split ジョブを INSERT する（status = queued）
    # API は jobs.status を UPDATE しない
    job = Job(
        id=job_id,
        video_id=video_id,
        type="split",
        status="queued",
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()

    # Redis Queue に job_id を enqueue する
    redis_client.rpush(SPLIT_QUEUE, job_id)

    # プレイヤーページにリダイレクトする
    return RedirectResponse(url=f"/player/{video_id}", status_code=303)


# --------------------------------------------------------------
# プレイヤーエンドポイント
# --------------------------------------------------------------

@app.get("/player/{video_id}", response_class=HTMLResponse)
async def player_page(
    request: Request,
    video_id: str,
    _user: str = Depends(require_login),
    db: Session = Depends(get_db),
):
    """
    動画プレイヤーページを返す。未認証の場合は /login にリダイレクト。

    プレイヤーページは hls.js を使って HLS 動画を再生する。
    実際の HLS ファイルへのアクセスは署名付きURL（/api/videos/{id}/url）
    を通じて行い、Nginx の secure_link_md5 で保護される。

    ジョブが存在しない場合（移行前の既存動画）は completed として扱う。

    Args:
        request:  FastAPI リクエストオブジェクト
        video_id: 動画の UUID
        _user:    ログイン確認用依存関数
        db:       データベースセッション

    Returns:
        HTMLResponse: プレイヤーページ HTML
    """
    # データベースから動画メタ情報を取得する
    video = db.query(Video).filter(Video.id == video_id).first()

    if not video:
        # 動画が見つからない場合は 404 ページを返す
        return HTMLResponse(
            content="<h1>404 - 動画が見つかりません</h1>",
            status_code=404,
        )

    # split ジョブの状態を取得する
    job = db.query(Job).filter(Job.video_id == video_id, Job.type == "split").first()
    # ジョブが存在しない場合（移行前の既存動画）は completed として扱う
    job_id = job.id if job else None
    job_status = job.status if job else "completed"

    return templates.TemplateResponse(
        request,
        "player.html",
        {
            "video_id": video_id,
            "title": video.title,
            "job_id": job_id,
            "job_status": job_status,
        },
    )


# --------------------------------------------------------------
# 署名付きURL生成エンドポイント
# --------------------------------------------------------------

@app.get("/api/videos/{video_id}/url")
async def get_signed_url(
    video_id: str,
    _user: str = Depends(require_login),
):
    """
    Nginx の secure_link_md5 と互換性のある署名付き HLS プレイリスト URL を返す。

    hls.js はプレイヤーページのロード時にこのエンドポイントを呼び出し、
    返された URL を使って /videos/{id}/playlist.m3u8 にアクセスする。

    返却 JSON:
        {"url": "/videos/{id}/playlist.m3u8?expires={TS}&md5={SIG}"}

    署名の計算は generate_signed_url() 関数に委譲する。

    Args:
        video_id: 動画の UUID
        _user:    ログイン確認用依存関数

    Returns:
        JSONResponse: 署名付き URL を含む JSON レスポンス
    """
    # 署名付きセグメントを埋め込んだプレイリストを返すプロキシエンドポイントを利用する
    # クライアントはこの URL を読み込み、返却されるプレイリスト内の各セグメントに
    # expires/md5 が付与されているため、そのまま nginx から取得できる。
    proxy_url = f"/api/videos/{video_id}/playlist"
    return JSONResponse({"url": proxy_url})


@app.get("/api/videos/{video_id}/playlist")
async def proxy_signed_playlist(
    video_id: str,
    _user: str = Depends(require_login),
):
    """
    MinIO に保存された playlist.m3u8 を読み込み、各セグメント URI に
    Nginx の secure_link_md5 と互換性のある署名（expires, md5）を付与して返す。

    これによりブラウザは署名付きのセグメント URL を直接 Nginx に要求できる。
    Nginx は secure_link 検証後に MinIO へ直接 proxy_pass してセグメントを返す。

    MinIO のオブジェクトキー: hls/{video_id}/playlist.m3u8
    """
    bucket = os.environ.get("MINIO_BUCKET", "minitube")
    playlist_key = f"hls/{video_id}/playlist.m3u8"

    s3 = _get_s3_client()
    try:
        response = s3.get_object(Bucket=bucket, Key=playlist_key)
        raw_content = response["Body"].read().decode("utf-8")
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ("NoSuchKey", "404", "NoSuchBucket"):
            return HTMLResponse(content="<h1>404 - playlist not found</h1>", status_code=404)
        raise

    secret_key = os.environ.get("SECRET_KEY", "changeme_replace_in_production")
    expires = int(time.time()) + 3600

    # プレイリストを読み込み、セグメント行（# で始まらない行）を署名付き URL に置換
    lines = raw_content.splitlines()

    out_lines = []
    for line in lines:
        if not line or line.startswith("#"):
            out_lines.append(line)
            continue

        # 相対パス（例: segment000.ts, segment001.ts）や同ディレクトリの参照を想定
        seg_path = line.strip()

        # 絶対 URL（http(s)://）や外部参照はそのまま渡す
        if seg_path.startswith("http://") or seg_path.startswith("https://"):
            out_lines.append(seg_path)
            continue

        # Nginx に対する URI を組み立てる（先頭スラッシュ付き）
        # /videos/{video_id}/{seg_name} → Nginx が secure_link 検証後 MinIO に proxy
        uri = f"/videos/{video_id}/{seg_path}"

        # Nginx と同じ方法で署名を計算する
        # 形式: md5(expires + uri + SECRET_KEY)
        raw = f"{expires}{uri}{secret_key}"
        digest = hashlib.md5(raw.encode("utf-8")).digest()  # noqa: S324
        sig = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")

        signed_uri = f"{uri}?expires={expires}&md5={sig}"
        out_lines.append(signed_uri)

    content = "\n".join(out_lines) + "\n"

    return HTMLResponse(content=content, media_type="application/vnd.apple.mpegurl")


# --------------------------------------------------------------
# ジョブ状態取得エンドポイント
# --------------------------------------------------------------

@app.get("/api/job/{job_id}")
async def get_job_status(
    job_id: str,
    _user: str = Depends(require_login),
    db: Session = Depends(get_db),
):
    """
    指定したジョブの状態を返す。

    UI がこのエンドポイントを定期的にポーリングして動画の処理状態を確認する。

    返却 JSON:
        {
            "job_id": "...",
            "video_id": "...",
            "status": "queued" | "processing" | "completed" | "error",
            "error_message": null | "..."
        }

    Args:
        job_id: ジョブの UUID
        _user:  ログイン確認用依存関数
        db:     データベースセッション

    Returns:
        JSONResponse: ジョブ状態を含む JSON レスポンス
    """
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        return JSONResponse({"error": "job not found"}, status_code=404)

    return JSONResponse({
        "job_id": job.id,
        "video_id": job.video_id,
        "status": job.status,
        "error_message": job.error_message,
    })
