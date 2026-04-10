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
     mp4 を受け取り、ffmpeg で HLS に変換して /videos/{id}/ に保存する

3. 動画プレイヤー
   - /player/{id}    : プレイヤーページ（HTML）

4. 署名付きURL生成（secure_link_md5）
   - /api/videos/{id}/url : 署名付き HLS プレイリスト URL を返す
     Nginx の secure_link_md5 と互換性のある md5 署名を付与する

技術的なポイント:
   - 認証は FastAPI の Cookie セッション（itsdangerous で署名）で完結する
   - Nginx は認証を行わず、HLS ファイルの署名検証のみを担当する
   - SECRET_KEY は環境変数から取得し、コードには直書きしない
   - データベースは PostgreSQL を使用し、SQLAlchemy ORM 経由でアクセスする
   - マイグレーションは Alembic で管理し、起動時に自動適用する
"""

import base64
import hashlib
import os
import secrets
import shutil
import subprocess
import time
import uuid

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import BigInteger, Column, String, create_engine
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
# HLS 変換ユーティリティ（ffmpeg）
# ==============================================================

def convert_to_hls(input_path: str, output_dir: str, video_id: str) -> None:
    """
    ffmpeg を使って mp4 ファイルを HLS 形式に変換する。

    出力ファイル:
        /videos/{id}/playlist.m3u8  - HLS プレイリスト（マスターファイル）
        /videos/{id}/segment000.ts  - セグメントファイル（4 秒ごと）
        /videos/{id}/segment001.ts
        ...

    ffmpeg オプションの説明:
        -i input_path         : 入力ファイルの指定
        -c:v libx264          : 映像を H.264 でエンコード（HLS との互換性を確保）
        -c:a aac              : 音声を AAC でエンコード（HLS との互換性を確保）
        -start_number 0       : セグメント番号を 0 から開始する
        -hls_time 4           : 各セグメントの長さを 4 秒にする
        -hls_list_size 0      : プレイリストにすべてのセグメントを記録する（VOD 用）
        -hls_segment_filename : セグメントファイルの命名パターン
        -f hls                : 出力フォーマットを HLS に指定

    Args:
        input_path: 入力 mp4 ファイルのフルパス
        output_dir: HLS ファイルの出力先ディレクトリ
        video_id:   動画の UUID（ログ表示用）

    Raises:
        RuntimeError: ffmpeg の実行が失敗した場合
    """
    playlist_path = os.path.join(output_dir, "playlist.m3u8")
    segment_pattern = os.path.join(output_dir, "segment%03d.ts")

    # ffmpeg コマンドを組み立てる
    command = [
        "ffmpeg",
        "-i", input_path,
        # 映像: H.264 エンコード（HLS/ブラウザとの互換性確保）
        "-c:v", "libx264",
        # 音声: AAC エンコード（ブラウザでの再生互換性確保）
        "-c:a", "aac",
        # セグメント番号を 0 から開始
        "-start_number", "0",
        # セグメント長を 4 秒に設定
        "-hls_time", "4",
        # VOD（録画配信）のため、すべてのセグメントをプレイリストに記録
        "-hls_list_size", "0",
        # セグメントファイルの命名パターン（例: segment000.ts）
        "-hls_segment_filename", segment_pattern,
        # 出力フォーマットを HLS に指定
        "-f", "hls",
        playlist_path,
    ]

    # ffmpeg を実行する
    # check=True にすると失敗時に CalledProcessError が発生するが、
    # ここでは stderr を取得したいので手動で確認する
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # ffmpeg のエラーメッセージを含めて例外を発生させる
        raise RuntimeError(
            f"ffmpeg による HLS 変換に失敗しました（video_id={video_id}）\n"
            f"stderr: {result.stderr}"
        )


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

    return templates.TemplateResponse(
        request,
        "upload.html",
        {
            "videos": [
                {"id": v.id, "title": v.title, "created_at": v.created_at}
                for v in videos
            ],
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
    mp4 ファイルをアップロードし、ffmpeg で HLS に変換して保存する。

    処理の流れ:
        1. アップロードされた mp4 を /tmp/{uuid}.mp4 に一時保存
        2. ffmpeg を実行して /videos/{uuid}/ 以下に HLS ファイルを出力
        3. PostgreSQL に動画メタ情報（id, title, created_at）を保存
        4. /player/{uuid} にリダイレクト
        5. 一時ファイル（/tmp/{uuid}.mp4）を削除

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

    # HLS 出力先ディレクトリを作成する
    output_dir = os.path.join(VIDEOS_DIR, video_id)
    os.makedirs(output_dir, exist_ok=True)

    # アップロードされた mp4 を一時ファイルに保存する
    # /tmp は Docker コンテナ内の一時領域であり、Nginx とは共有しない
    tmp_path = f"/tmp/{video_id}.mp4"
    try:
        with open(tmp_path, "wb") as tmp_file:
            shutil.copyfileobj(file.file, tmp_file)

        # ffmpeg を使って HLS に変換する
        # 変換失敗時は RuntimeError が発生する
        convert_to_hls(
            input_path=tmp_path,
            output_dir=output_dir,
            video_id=video_id,
        )
    finally:
        # 変換成功・失敗にかかわらず一時ファイルを削除する
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    # PostgreSQL に動画メタ情報を保存する
    video = Video(
        id=video_id,
        title=file.filename or "無題",
        created_at=int(time.time()),
    )
    db.add(video)
    db.commit()

    # 変換完了後、プレイヤーページにリダイレクトする
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

    return templates.TemplateResponse(
        request,
        "player.html",
        {
            "video_id": video_id,
            "title": video.title,
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
    ローカルに保存された playlist.m3u8 を読み込み、各セグメント URI に
    Nginx の secure_link_md5 と互換性のある署名（expires, md5）を付与して返す。

    これによりブラウザは署名付きのセグメント URL を直接 Nginx に要求できる。
    """
    playlist_path = os.path.join(VIDEOS_DIR, video_id, "playlist.m3u8")

    if not os.path.exists(playlist_path):
        return HTMLResponse(content="<h1>404 - playlist not found</h1>", status_code=404)

    secret_key = os.environ.get("SECRET_KEY", "changeme_replace_in_production")
    expires = int(time.time()) + 3600

    # プレイリストを読み込み、セグメント行（# で始まらない行）を署名付き URL に置換
    with open(playlist_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

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
        uri = f"/videos/{video_id}/{seg_path}"

        # Nginx と同じ方法で署名を計算する
        raw = f"{expires}{uri}{secret_key}"
        digest = hashlib.md5(raw.encode("utf-8")).digest()  # noqa: S324
        sig = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")

        signed_uri = f"{uri}?expires={expires}&md5={sig}"
        out_lines.append(signed_uri)

    content = "\n".join(out_lines) + "\n"

    return HTMLResponse(content=content, media_type="application/vnd.apple.mpegurl")
