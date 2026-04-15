"""
minitube - 最小構成の動画配信 Web アプリ（FastAPI バックエンド）

このモジュールは以下の機能を提供する:

1. 認証（Cookie ベースのセッション管理）
   - /login          : ログインページ（HTML）
   - /api/login      : ログイン処理（POST）
   - /logout         : ログアウト処理
   - /register       : ユーザ登録ページ（HTML）
   - /api/register   : ユーザ登録処理（POST）

2. 動画アップロード
   - /upload         : アップロードページ（HTML）
   - /api/upload     : アップロード処理（POST）→ /videos/{id}/edit へリダイレクト

3. ホーム・動画一覧・プレイヤー
   - /home           : ホーム画面（視聴者向け。未ログインは公開動画のみ。公開動画なし→/login）
   - /videos         : 動画一覧ページ（公開動画は未ログインでも閲覧可）
   - /player/{id}    : プレイヤーページ（公開動画は未ログインでも閲覧可）

4. 動画編集
   - /videos/{id}/edit            : 動画編集ページ（オーナー/Admin のみ）
   - /api/videos/{id}/update      : 動画メタ情報更新（POST）
   - /api/videos/{id}/delete      : 動画削除（POST）
   - /api/videos/{id}/replace     : 動画ファイル差し替え（POST）
   - /api/videos/{id}/clear_cache : Nginx キャッシュ削除（POST）

5. 署名付きURL生成（secure_link_md5）
   - /api/videos/{id}/url      : 署名付き HLS プレイリスト URL を返す
   - /api/videos/{id}/playlist : セグメント署名付きプレイリストを返す

6. ジョブ状態取得
   - /api/job/{job_id} : ジョブ状態を返す

7. プロフィール編集・ロール管理
   - /profile                  : プロフィール表示・編集ページ（表示名・アイコン・パスワード）
   - /api/profile/update       : 表示名・アイコン更新（POST）
   - /api/profile/password     : パスワード変更（POST）
   - /admin/users           : Admin 専用ユーザ管理ページ
   - /api/admin/users/{id}/roles : ロール付与（POST）
   - /api/admin/users/{id}/roles/{role} : ロール削除（DELETE）

8. 動画権限管理
   - /api/admin/videos/{id}/permissions : 視聴権限付与（POST）
   - /api/admin/videos/{id}/permissions/{user_id} : 視聴権限削除（DELETE）

9. カテゴリ管理（Admin のみ）
   - /admin/categories                      : カテゴリ管理ページ（HTML）
   - /api/admin/categories                  : カテゴリ作成（POST）
   - /api/admin/categories/{id}/update      : カテゴリ名変更（POST）
   - /api/admin/categories/{id}/delete      : カテゴリ削除（POST）

10. 視聴履歴
    - /api/videos/{id}/watch    : 再生開始時に履歴を作成・更新（POST）
    - /api/videos/{id}/progress : 再生位置を更新（POST）
    - /api/videos/{id}/complete : 視聴完了を記録（POST）
    - /api/users/me/history     : 最近見た動画一覧（GET）
    - /api/users/me/resume      : 続きから再生できる動画一覧（GET）
"""

import base64
import hashlib
import logging
import os
import re
import secrets
import shutil
import time
import boto3
import redis as redis_lib
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from utils.id_generator import generate_base62_id

logger = logging.getLogger("minitube")
logging.basicConfig(level=logging.INFO)

# ==============================================================
# アプリケーション初期化
# ==============================================================

app = FastAPI(title="minitube", description="最小構成の動画配信 Web アプリ")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "changeme_replace_in_production"),
    same_site="lax",
    https_only=False,
)

templates = Jinja2Templates(directory="templates")

VIDEOS_DIR = "/videos"
SPLIT_QUEUE = "split_jobs"

# ==============================================================
# データベース設定（SQLAlchemy + PostgreSQL）
# ==============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://minitube:changeme_replace_in_production@db/minitube",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class Base(DeclarativeBase):
    pass


class User(Base):
    """ユーザ情報を保持する ORM モデル。"""
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(BigInteger, nullable=False)
    display_name = Column(String(50), nullable=True)
    icon_path = Column(String, nullable=True)


class Role(Base):
    """ロール（admin/uploader/viewer）を保持する ORM モデル。"""
    __tablename__ = "roles"
    id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False)


class UserRole(Base):
    """ユーザとロールの多対多関係を表す ORM モデル。"""
    __tablename__ = "user_roles"
    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    role_id = Column(String, ForeignKey("roles.id"), primary_key=True)


class Category(Base):
    """カテゴリを保持する ORM モデル。"""
    __tablename__ = "categories"
    id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    created_at = Column(BigInteger, nullable=False)


class Video(Base):
    """動画メタ情報を保持する ORM モデル。"""
    __tablename__ = "videos"
    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    owner_user_id = Column(String, nullable=True)
    description = Column(String, nullable=True)
    category_id = Column(String, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    visibility = Column(String, nullable=False, default="public")
    status = Column(String, nullable=False, default="ready")
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=True)


class Job(Base):
    """動画処理ジョブの状態を管理する ORM モデル。"""
    __tablename__ = "jobs"
    id = Column(String, primary_key=True)
    video_id = Column(String, nullable=False)
    type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="queued")
    error_message = Column(String, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    __table_args__ = (
        UniqueConstraint("video_id", "type", name="uq_jobs_video_id_type"),
    )


class VideoPermission(Base):
    """動画の視聴権限を表す ORM モデル（Private 動画の閲覧許可）。"""
    __tablename__ = "video_permissions"
    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    video_id = Column(String, ForeignKey("videos.id"), primary_key=True)


class Thumbnail(Base):
    """動画サムネイルを保持する ORM モデル（video : thumbnail = 1 : n）。"""
    __tablename__ = "thumbnails"
    id = Column(String, primary_key=True)
    video_id = Column(String, ForeignKey("videos.id", ondelete="CASCADE"), nullable=False)
    url = Column(Text, nullable=False)
    type = Column(String, nullable=False)
    active = Column(Boolean, nullable=False, default=False)
    created_at = Column(BigInteger, nullable=False)


class WatchHistory(Base):
    """視聴履歴を保持する ORM モデル（ユーザ × 動画 = 1 行）。"""
    __tablename__ = "watch_history"
    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    video_id = Column(String, ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True)
    last_watched_at = Column(BigInteger, nullable=False)
    last_position = Column(Integer, nullable=False, default=0)
    duration = Column(Integer, nullable=True)
    completed = Column(Boolean, nullable=False, default=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Base62 ID 形式の検証パターン（11 文字の [0-9A-Za-z]）
_BASE62_ID_RE = re.compile(r'^[0-9A-Za-z]{11}$')


def _is_valid_id(value: str) -> bool:
    """文字列が Base62 ID 形式（11 文字）かどうかを検証する。パストラバーサル攻撃を防ぐ。"""
    return bool(_BASE62_ID_RE.match(value))


# ==============================================================
# Redis クライアント設定
# ==============================================================

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
redis_client = redis_lib.from_url(REDIS_URL)


# ==============================================================
# MinIO クライアント設定
# ==============================================================

def _get_s3_client():
    endpoint = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
    access_key = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.environ.get("MINIO_SECRET_KEY", "changeme_minio_secret")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


# ==============================================================
# パスワードハッシュユーティリティ
# ==============================================================

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ==============================================================
# システム初期化（起動時）
# ==============================================================

ADMIN_EMAIL = "admin@example.com"
ROLE_NAMES = ["admin", "uploader", "viewer"]


@app.on_event("startup")
async def startup_event():
    """
    FastAPI 起動時に以下を冪等に実行する:
    1. roles テーブルに admin/uploader/viewer を作成
    2. admin ユーザを作成（存在しない場合のみ）
    3. admin ロールを付与（存在しない場合のみ）
    パスワードは INITIAL_ADMIN_PASSWORD 環境変数から取得し、
    初回のみ設定する（再起動時は上書きしない）。
    """
    db = SessionLocal()
    try:
        # 1. ロールを作成（存在しない場合のみ）
        role_map = {}
        for role_name in ROLE_NAMES:
            role = db.query(Role).filter(Role.name == role_name).first()
            if not role:
                role = Role(id=generate_base62_id(), name=role_name)
                db.add(role)
                logger.info(f"[init] ロール作成: {role_name}")
            role_map[role_name] = role
        db.flush()

        # 2. admin ユーザを作成（存在しない場合のみ）
        admin_user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if not admin_user:
            initial_password = os.environ.get("INITIAL_ADMIN_PASSWORD", "admin")
            admin_user = User(
                id=generate_base62_id(),
                email=ADMIN_EMAIL,
                password_hash=hash_password(initial_password),
                created_at=int(time.time()),
            )
            db.add(admin_user)
            db.flush()
            logger.info(f"[init] admin ユーザ作成: {ADMIN_EMAIL}")
        else:
            logger.info(f"[init] admin ユーザ既存（パスワード更新なし）: {ADMIN_EMAIL}")

        # 3. admin ロールを付与（存在しない場合のみ）
        admin_role = role_map["admin"]
        existing_user_role = db.query(UserRole).filter(
            UserRole.user_id == admin_user.id,
            UserRole.role_id == admin_role.id,
        ).first()
        if not existing_user_role:
            db.add(UserRole(user_id=admin_user.id, role_id=admin_role.id))
            logger.info(f"[init] admin ロール付与: {ADMIN_EMAIL}")

        db.commit()
        logger.info("[init] 初期化完了")
    except Exception as e:
        db.rollback()
        logger.error(f"[init] 初期化エラー: {e}")
        raise
    finally:
        db.close()


# ==============================================================
# 認証ユーティリティ
# ==============================================================

class NotAuthenticated(Exception):
    pass


class Forbidden(Exception):
    pass


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url="/login", status_code=303)


@app.exception_handler(Forbidden)
async def forbidden_handler(request: Request, exc: Forbidden):
    return HTMLResponse(content="<h1>403 - アクセス権限がありません</h1>", status_code=403)


def get_current_user(request: Request) -> dict | None:
    """セッションからユーザ情報を取得する。未ログインの場合は None を返す。"""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return {
        "user_id": user_id,
        "email": request.session.get("email", ""),
        "roles": request.session.get("roles", []),
    }


def require_login(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise NotAuthenticated()
    return user


def require_admin(request: Request) -> dict:
    user = get_current_user(request)
    if not user or "admin" not in user["roles"]:
        raise NotAuthenticated()
    return user


def get_user_roles(user_id: str, db: Session) -> list[str]:
    """ユーザのロール名リストを取得する。"""
    rows = (
        db.query(Role.name)
        .join(UserRole, Role.id == UserRole.role_id)
        .filter(UserRole.user_id == user_id)
        .all()
    )
    return [r[0] for r in rows]


def can_view_video(video, user: dict | None, db: Session) -> bool:
    """動画を視聴できるか判定する。"""
    if video.visibility == "public":
        return True
    if user is None:
        return False
    if "admin" in user["roles"]:
        return True
    if video.owner_user_id == user["user_id"]:
        return True
    perm = db.query(VideoPermission).filter(
        VideoPermission.user_id == user["user_id"],
        VideoPermission.video_id == video.id,
    ).first()
    return perm is not None


# ==============================================================
# 署名付きURL生成ユーティリティ
# ==============================================================

def generate_signed_url(video_id: str) -> str:
    secret_key = os.environ.get("SECRET_KEY", "changeme_replace_in_production")
    expires = int(time.time()) + 3600
    uri = f"/videos/{video_id}/playlist.m3u8"
    raw_string = f"{expires}{uri}{secret_key}"
    digest = hashlib.md5(raw_string.encode("utf-8")).digest()  # noqa: S324
    signature = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return f"{uri}?expires={expires}&md5={signature}"


# ==============================================================
# ルート定義
# ==============================================================

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/home", status_code=302)


# --------------------------------------------------------------
# ホームエンドポイント
# --------------------------------------------------------------

@app.get("/home", response_class=HTMLResponse)
async def home_page(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request)

    # クエリを絞り込む（status が ready のみ）
    query = db.query(Video).filter(Video.status == "ready")
    if not current_user:
        # 未ログインユーザには公開動画のみを返す
        query = query.filter(Video.visibility == "public")
    all_videos = query.order_by(Video.created_at.desc()).all()

    # ログイン済みの場合は権限チェックが必要（admin/owner/permission）
    if current_user:
        filtered = [v for v in all_videos if can_view_video(v, current_user, db)]
    else:
        filtered = all_videos

    if not current_user and not filtered:
        return RedirectResponse(url="/login", status_code=303)

    # アクティブなサムネイルを一括取得（N+1 を避ける）
    video_ids = [v.id for v in filtered]
    thumb_map: dict[str, str] = {}
    if video_ids:
        active_thumbs = db.query(Thumbnail).filter(
            Thumbnail.video_id.in_(video_ids),
            Thumbnail.active.is_(True),
        ).all()
        for t in active_thumbs:
            thumb_map[t.video_id] = t.url

    visible_videos = [
        {
            "id": v.id,
            "title": v.title,
            "thumbnail_url": thumb_map.get(v.id),
        }
        for v in filtered
    ]

    # 視聴履歴セクション（ログイン済みの場合のみ）
    recent_history: list[dict] = []
    resume_history: list[dict] = []
    if current_user:
        history_rows = (
            db.query(WatchHistory, Video)
            .join(Video, WatchHistory.video_id == Video.id)
            .filter(
                WatchHistory.user_id == current_user["user_id"],
                Video.status == "ready",
            )
            .order_by(WatchHistory.last_watched_at.desc())
            .limit(10)
            .all()
        )
        # 視聴可能な動画のみに絞り込み、サムネイルも付与する
        history_video_ids = [v.id for _, v in history_rows]
        history_thumb_map: dict[str, str] = {}
        if history_video_ids:
            history_thumbs = db.query(Thumbnail).filter(
                Thumbnail.video_id.in_(history_video_ids),
                Thumbnail.active.is_(True),
            ).all()
            for t in history_thumbs:
                history_thumb_map[t.video_id] = t.url

        for h, v in history_rows:
            if not can_view_video(v, current_user, db):
                continue
            entry = {
                "id": v.id,
                "title": v.title,
                "thumbnail_url": history_thumb_map.get(v.id),
                "last_watched_at": h.last_watched_at,
                "last_position": h.last_position,
                "duration": h.duration,
                "completed": h.completed,
            }
            recent_history.append(entry)
            if h.last_position > 0:
                resume_history.append(entry)

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "videos": visible_videos,
            "current_user": current_user,
            "is_admin": current_user and "admin" in current_user["roles"],
            "is_uploader": current_user and "uploader" in current_user["roles"],
            "recent_history": recent_history,
            "resume_history": resume_history,
        },
    )


# --------------------------------------------------------------
# 認証エンドポイント
# --------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if request.session.get("user_id"):
        return RedirectResponse(url="/home", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": error == "1"})


@app.post("/api/login")
async def api_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return RedirectResponse(url="/login?error=1", status_code=303)
    roles = get_user_roles(user.id, db)
    request.session["user_id"] = user.id
    request.session["email"] = user.email
    request.session["roles"] = roles
    return RedirectResponse(url="/home", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, error: str = ""):
    if request.session.get("user_id"):
        return RedirectResponse(url="/home", status_code=303)
    return templates.TemplateResponse(request, "register.html", {"error": error})


@app.post("/api/register")
async def api_register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return RedirectResponse(url="/register?error=already_exists", status_code=303)
    now = int(time.time())
    user = User(
        id=generate_base62_id(),
        email=email,
        password_hash=hash_password(password),
        created_at=now,
    )
    db.add(user)
    db.flush()
    # Viewer ロールを付与
    viewer_role = db.query(Role).filter(Role.name == "viewer").first()
    if viewer_role:
        db.add(UserRole(user_id=user.id, role_id=viewer_role.id))
    db.commit()
    return RedirectResponse(url="/login", status_code=303)


# --------------------------------------------------------------
# プロフィール
# --------------------------------------------------------------

ICON_BUCKET = os.environ.get("MINIO_BUCKET", "minitube")
ICON_MAX_BYTES = 1 * 1024 * 1024  # 1 MB
ICON_ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg"}


def _get_icon_url(icon_path: str | None) -> str | None:
    """MinIO のアイコンオブジェクトキーから Nginx 経由でアクセスできる URL パスを返す。"""
    if not icon_path:
        return None
    # icon_path は "user-icons/{user_id}.{ext}" 形式
    # Nginx の /user-icons/ ロケーションが MinIO へ proxy_pass する
    return f"/{icon_path}"


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    user: dict = Depends(require_login),
    db: Session = Depends(get_db),
):
    db_user = db.query(User).filter(User.id == user["user_id"]).first()
    display_name = db_user.display_name if db_user else ""
    icon_url = _get_icon_url(db_user.icon_path if db_user else None)
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "email": user["email"],
            "roles": user["roles"],
            "display_name": display_name or "",
            "icon_url": icon_url,
            "is_admin": "admin" in user["roles"],
            "is_uploader": "uploader" in user["roles"],
        },
    )


@app.post("/api/profile/update")
async def api_profile_update(
    request: Request,
    display_name: str = Form(""),
    icon: UploadFile | None = File(None),
    user: dict = Depends(require_login),
    db: Session = Depends(get_db),
):
    """表示名・アイコン画像を更新する（ログインユーザのみ）。"""
    db_user = db.query(User).filter(User.id == user["user_id"]).first()
    if not db_user:
        return RedirectResponse(url="/profile?error=user_not_found", status_code=303)

    # 表示名のバリデーション（最大 50 文字）
    display_name = display_name.strip()
    if len(display_name) > 50:
        return RedirectResponse(url="/profile?error=display_name_too_long", status_code=303)
    db_user.display_name = display_name or None

    # アイコン画像のアップロード
    if icon and icon.filename:
        content_type = icon.content_type or ""
        if content_type not in ICON_ALLOWED_CONTENT_TYPES:
            return RedirectResponse(url="/profile?error=invalid_icon_type", status_code=303)
        icon_data = await icon.read()
        if len(icon_data) > ICON_MAX_BYTES:
            return RedirectResponse(url="/profile?error=icon_too_large", status_code=303)
        ext = "png" if content_type == "image/png" else "jpg"
        icon_key = f"user-icons/{db_user.id}.{ext}"
        s3 = _get_s3_client()
        # 拡張子が変わった場合は古いアイコンを削除する
        if db_user.icon_path and db_user.icon_path != icon_key:
            try:
                s3.delete_object(Bucket=ICON_BUCKET, Key=db_user.icon_path)
            except ClientError:
                pass
        try:
            s3.put_object(
                Bucket=ICON_BUCKET,
                Key=icon_key,
                Body=icon_data,
                ContentType=content_type,
            )
        except ClientError as e:
            logger.error("Failed to upload icon: %s", e)
            return RedirectResponse(url="/profile?error=icon_upload_failed", status_code=303)
        db_user.icon_path = icon_key

    db.commit()
    return RedirectResponse(url="/profile?success=profile_updated", status_code=303)


@app.post("/api/profile/password")
async def api_profile_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user: dict = Depends(require_login),
    db: Session = Depends(get_db),
):
    """パスワードを変更する（ログインユーザのみ）。"""
    db_user = db.query(User).filter(User.id == user["user_id"]).first()
    if not db_user:
        return RedirectResponse(url="/profile?error=user_not_found", status_code=303)
    if not verify_password(current_password, db_user.password_hash):
        return RedirectResponse(url="/profile?error=wrong_current_password", status_code=303)
    if new_password != confirm_password:
        return RedirectResponse(url="/profile?error=password_mismatch", status_code=303)
    if len(new_password) < 8:
        return RedirectResponse(url="/profile?error=password_too_short", status_code=303)
    db_user.password_hash = hash_password(new_password)
    db.commit()
    return RedirectResponse(url="/profile?success=password_changed", status_code=303)


# --------------------------------------------------------------
# Admin ユーザ管理
# --------------------------------------------------------------

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(
    request: Request,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    all_users = db.query(User).order_by(User.created_at).all()
    all_roles = db.query(Role).all()
    users_with_roles = []
    for u in all_users:
        roles = get_user_roles(u.id, db)
        users_with_roles.append({
            "id": u.id,
            "email": u.email,
            "roles": roles,
            "is_admin_account": u.email == ADMIN_EMAIL,
        })
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            "users": users_with_roles,
            "all_roles": [r.name for r in all_roles],
            "is_admin": True,
        },
    )


@app.post("/api/admin/users/{user_id}/roles")
async def add_role_to_user(
    user_id: str,
    role_name: str = Form(...),
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.name == role_name).first()
    if not role:
        return JSONResponse({"error": "role not found"}, status_code=404)
    existing = db.query(UserRole).filter(
        UserRole.user_id == user_id, UserRole.role_id == role.id
    ).first()
    if not existing:
        db.add(UserRole(user_id=user_id, role_id=role.id))
        db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@app.post("/api/admin/users/{user_id}/roles/{role_name}/delete")
async def remove_role_from_user(
    user_id: str,
    role_name: str,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # admin@example.com の admin ロールは削除不可
    target_user = db.query(User).filter(User.id == user_id).first()
    if target_user and target_user.email == ADMIN_EMAIL and role_name == "admin":
        return JSONResponse({"error": "cannot remove admin role from admin account"}, status_code=400)
    role = db.query(Role).filter(Role.name == role_name).first()
    if role:
        db.query(UserRole).filter(
            UserRole.user_id == user_id, UserRole.role_id == role.id
        ).delete()
        db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


# --------------------------------------------------------------
# 動画権限管理
# --------------------------------------------------------------

@app.post("/api/admin/videos/{video_id}/permissions")
async def add_video_permission(
    video_id: str,
    email: str = Form(...),
    user: dict = Depends(require_login),
    db: Session = Depends(get_db),
):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return JSONResponse({"error": "video not found"}, status_code=404)
    # Admin または動画オーナーのみ権限付与可能
    if "admin" not in user["roles"] and video.owner_user_id != user["user_id"]:
        raise Forbidden()
    target_user = db.query(User).filter(User.email == email).first()
    if not target_user:
        return JSONResponse({"error": "user not found"}, status_code=404)
    existing = db.query(VideoPermission).filter(
        VideoPermission.user_id == target_user.id,
        VideoPermission.video_id == video_id,
    ).first()
    if not existing:
        db.add(VideoPermission(user_id=target_user.id, video_id=video_id))
        db.commit()
    return RedirectResponse(url=f"/player/{video.id}", status_code=303)


@app.post("/api/admin/videos/{video_id}/permissions/{target_user_id}/delete")
async def remove_video_permission(
    video_id: str,
    target_user_id: str,
    user: dict = Depends(require_login),
    db: Session = Depends(get_db),
):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return JSONResponse({"error": "video not found"}, status_code=404)
    if "admin" not in user["roles"] and video.owner_user_id != user["user_id"]:
        raise Forbidden()
    db.query(VideoPermission).filter(
        VideoPermission.user_id == target_user_id,
        VideoPermission.video_id == video_id,
    ).delete()
    db.commit()
    return RedirectResponse(url=f"/player/{video.id}", status_code=303)


# --------------------------------------------------------------
# 動画一覧
# --------------------------------------------------------------

@app.get("/videos", response_class=HTMLResponse)
async def videos_page(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request)
    if not current_user or (
        "admin" not in current_user["roles"] and "uploader" not in current_user["roles"]
    ):
        return RedirectResponse(url="/home", status_code=303)
    all_videos = db.query(Video).order_by(Video.created_at.desc()).all()
    visible_videos = []
    for v in all_videos:
        if can_view_video(v, current_user, db):
            job = db.query(Job).filter(Job.video_id == v.id, Job.type == "split").first()
            status = job.status if job else "completed"
            # オーナーのemailを取得
            owner_email = None
            if v.owner_user_id:
                owner = db.query(User).filter(User.id == v.owner_user_id).first()
                if owner:
                    owner_email = owner.email
            can_edit = bool(
                current_user and (
                    "admin" in current_user["roles"]
                    or v.owner_user_id == current_user["user_id"]
                )
            )
            active_thumb = db.query(Thumbnail).filter(
                Thumbnail.video_id == v.id, Thumbnail.active.is_(True)
            ).first()
            visible_videos.append({
                "id": v.id,
                "title": v.title,
                "visibility": v.visibility,
                "owner_email": owner_email,
                "created_at": v.created_at,
                "status": status,
                "can_edit": can_edit,
                "thumbnail_url": active_thumb.url if active_thumb else None,
            })
    return templates.TemplateResponse(
        request,
        "videos.html",
        {
            "videos": visible_videos,
            "current_user": current_user,
            "is_admin": current_user and "admin" in current_user["roles"],
            "is_uploader": current_user and "uploader" in current_user["roles"],
        },
    )


# --------------------------------------------------------------
# アップロードエンドポイント
# --------------------------------------------------------------

@app.get("/upload", response_class=HTMLResponse)
async def upload_page(
    request: Request,
    user: dict = Depends(require_login),
):
    # Uploader または Admin のみアップロード可能
    if "uploader" not in user["roles"] and "admin" not in user["roles"]:
        raise Forbidden()
    return templates.TemplateResponse(
        request,
        "upload.html",
        {
            "is_admin": "admin" in user["roles"],
        },
    )


@app.post("/api/upload")
async def api_upload(
    request: Request,
    file: UploadFile = File(...),
    visibility: str = Form("public"),
    user: dict = Depends(require_login),
    db: Session = Depends(get_db),
):
    # Uploader または Admin のみアップロード可能
    if "uploader" not in user["roles"] and "admin" not in user["roles"]:
        raise Forbidden()
    video_id = generate_base62_id()
    job_id = generate_base62_id()
    now = int(time.time())
    output_dir = os.path.join(VIDEOS_DIR, video_id)
    os.makedirs(output_dir, exist_ok=True)
    input_path = os.path.join(output_dir, "input.mp4")
    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    # visibility の値を検証する
    if visibility not in ("public", "private"):
        visibility = "public"
    video = Video(
        id=video_id,
        title=file.filename or "無題",
        owner_user_id=user["user_id"],
        visibility=visibility,
        status="processing",
        created_at=now,
        updated_at=now,
    )
    db.add(video)
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
    redis_client.rpush(SPLIT_QUEUE, job_id)
    return RedirectResponse(url=f"/videos/{video_id}/edit", status_code=303)


# --------------------------------------------------------------
# プレイヤーエンドポイント
# --------------------------------------------------------------

@app.get("/player/{video_id}", response_class=HTMLResponse)
async def player_page(
    request: Request,
    video_id: str,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request)
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return HTMLResponse(content="<h1>404 - 動画が見つかりません</h1>", status_code=404)
    if not can_view_video(video, current_user, db):
        return HTMLResponse(content="<h1>403 - この動画を視聴する権限がありません</h1>", status_code=403)
    job = db.query(Job).filter(Job.video_id == video_id, Job.type == "split").first()
    job_id = job.id if job else None
    job_status = job.status if job else "completed"
    # 権限管理情報（admin またはオーナーのみ表示）
    can_manage = current_user and (
        "admin" in current_user["roles"] or video.owner_user_id == current_user["user_id"]
    )
    permissions = []
    if can_manage:
        perms = db.query(VideoPermission).filter(VideoPermission.video_id == video_id).all()
        for p in perms:
            u = db.query(User).filter(User.id == p.user_id).first()
            if u:
                permissions.append({"user_id": p.user_id, "email": u.email})
    return templates.TemplateResponse(
        request,
        "player.html",
        {
            "video_id": video_id,
            "title": video.title,
            "visibility": video.visibility,
            "job_id": job_id,
            "job_status": job_status,
            "current_user": current_user,
            "can_manage": can_manage,
            "permissions": permissions,
            "is_admin": current_user and "admin" in current_user["roles"],
            "is_uploader": current_user and "uploader" in current_user["roles"],
        },
    )


# --------------------------------------------------------------
# 署名付きURL生成エンドポイント
# --------------------------------------------------------------

@app.get("/api/videos/{video_id}/url")
async def get_signed_url(
    video_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request)
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not can_view_video(video, current_user, db):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    proxy_url = f"/api/videos/{video_id}/playlist"
    return JSONResponse({"url": proxy_url})


@app.get("/api/videos/{video_id}/playlist")
async def proxy_signed_playlist(
    video_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request)
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return HTMLResponse(content="<h1>404 - video not found</h1>", status_code=404)
    if not can_view_video(video, current_user, db):
        return HTMLResponse(content="<h1>403 - forbidden</h1>", status_code=403)
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
    lines = raw_content.splitlines()
    out_lines = []
    for line in lines:
        if not line or line.startswith("#"):
            out_lines.append(line)
            continue
        seg_path = line.strip()
        if seg_path.startswith("http://") or seg_path.startswith("https://"):
            out_lines.append(seg_path)
            continue
        uri = f"/videos/{video_id}/{seg_path}"
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
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        return JSONResponse({"error": "job not found"}, status_code=404)
    return JSONResponse({
        "job_id": job.id,
        "video_id": job.video_id,
        "status": job.status,
        "error_message": job.error_message,
    })


# ==============================================================
# MinIO HLS 削除ユーティリティ
# ==============================================================

def _delete_hls_from_minio(video_id: str) -> None:
    """MinIO から指定動画の HLS ファイルをすべて削除する。"""
    bucket = os.environ.get("MINIO_BUCKET", "minitube")
    s3 = _get_s3_client()
    prefix = f"hls/{video_id}/"
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            objects = page.get("Contents", [])
            if objects:
                s3.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
                )
    except ClientError:
        pass


def _delete_thumbnails_from_minio(video_id: str, db: Session) -> None:
    """MinIO から指定動画のサムネイルファイルをすべて削除する。"""
    bucket = os.environ.get("MINIO_BUCKET", "minitube")
    s3 = _get_s3_client()
    prefix = f"videos/{video_id}/thumbnails/"
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            objects = page.get("Contents", [])
            if objects:
                s3.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
                )
    except ClientError:
        pass


# ==============================================================
# カテゴリ管理（Admin 専用）
# ==============================================================

@app.get("/admin/categories", response_class=HTMLResponse)
async def admin_categories_page(
    request: Request,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """カテゴリ管理ページ（Admin のみ）。"""
    all_categories = db.query(Category).order_by(Category.created_at).all()
    categories_info = []
    for cat in all_categories:
        video_count = db.query(Video).filter(Video.category_id == cat.id).count()
        categories_info.append({
            "id": cat.id,
            "name": cat.name,
            "created_at": cat.created_at,
            "video_count": video_count,
        })
    return templates.TemplateResponse(
        request,
        "admin_categories.html",
        {
            "categories": categories_info,
            "is_admin": True,
        },
    )


@app.post("/api/admin/categories")
async def create_category(
    name: str = Form(...),
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """カテゴリを新規作成する（Admin のみ）。"""
    name = name.strip()
    if not name:
        return RedirectResponse(url="/admin/categories?error=empty_name", status_code=303)
    existing = db.query(Category).filter(Category.name == name).first()
    if existing:
        return RedirectResponse(url="/admin/categories?error=duplicate_name", status_code=303)
    cat = Category(id=generate_base62_id(), name=name, created_at=int(time.time()))
    db.add(cat)
    db.commit()
    return RedirectResponse(url="/admin/categories", status_code=303)


@app.post("/api/admin/categories/{category_id}/update")
async def update_category(
    category_id: str,
    name: str = Form(...),
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """カテゴリ名を変更する（Admin のみ）。"""
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        return JSONResponse({"error": "category not found"}, status_code=404)
    name = name.strip()
    if not name:
        return RedirectResponse(url="/admin/categories?error=empty_name", status_code=303)
    existing = db.query(Category).filter(Category.name == name, Category.id != category_id).first()
    if existing:
        return RedirectResponse(url="/admin/categories?error=duplicate_name", status_code=303)
    cat.name = name
    db.commit()
    return RedirectResponse(url="/admin/categories", status_code=303)


@app.post("/api/admin/categories/{category_id}/delete")
async def delete_category(
    category_id: str,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """カテゴリを削除する（Admin のみ）。動画が紐づいている場合は削除不可。"""
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        return JSONResponse({"error": "category not found"}, status_code=404)
    video_count = db.query(Video).filter(Video.category_id == category_id).count()
    if video_count > 0:
        return RedirectResponse(url="/admin/categories?error=has_videos", status_code=303)
    db.delete(cat)
    db.commit()
    return RedirectResponse(url="/admin/categories", status_code=303)


# ==============================================================
# 動画編集エンドポイント
# ==============================================================

@app.get("/videos/{video_id}/edit", response_class=HTMLResponse)
async def video_edit_page(
    request: Request,
    video_id: str,
    db: Session = Depends(get_db),
):
    """動画編集ページ（オーナーまたは Admin のみ）。"""
    if not _is_valid_id(video_id):
        return HTMLResponse(content="<h1>400 - 無効な動画 ID です</h1>", status_code=400)
    current_user = require_login(request)
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return HTMLResponse(content="<h1>404 - 動画が見つかりません</h1>", status_code=404)
    if "admin" not in current_user["roles"] and video.owner_user_id != current_user["user_id"]:
        raise Forbidden()
    job = db.query(Job).filter(Job.video_id == video.id, Job.type == "split").first()
    job_id = job.id if job else None
    all_categories = db.query(Category).order_by(Category.name).all()
    permissions = []
    perms = db.query(VideoPermission).filter(VideoPermission.video_id == video.id).all()
    for p in perms:
        u = db.query(User).filter(User.id == p.user_id).first()
        if u:
            permissions.append({"user_id": p.user_id, "email": u.email})
    thumbnails = db.query(Thumbnail).filter(Thumbnail.video_id == video.id).order_by(Thumbnail.created_at).all()
    return templates.TemplateResponse(
        request,
        "video_edit.html",
        {
            "video_id": video.id,
            "title": video.title,
            "description": video.description or "",
            "category_id": video.category_id or "",
            "visibility": video.visibility,
            "status": video.status,
            "job_id": job_id,
            "categories": [{"id": c.id, "name": c.name} for c in all_categories],
            "permissions": permissions,
            "thumbnails": [{"id": t.id, "url": t.url, "type": t.type, "active": t.active} for t in thumbnails],
            "current_user": current_user,
            "is_admin": "admin" in current_user["roles"],
            "is_uploader": "uploader" in current_user["roles"],
        },
    )


@app.post("/api/videos/{video_id}/update")
async def api_video_update(
    request: Request,
    video_id: str,
    title: str = Form(...),
    description: str = Form(""),
    category_id: str = Form(""),
    visibility: str = Form("public"),
    db: Session = Depends(get_db),
):
    """動画メタ情報を更新する（オーナーまたは Admin のみ）。"""
    if not _is_valid_id(video_id):
        return JSONResponse({"error": "invalid video_id"}, status_code=400)
    current_user = require_login(request)
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return JSONResponse({"error": "video not found"}, status_code=404)
    if "admin" not in current_user["roles"] and video.owner_user_id != current_user["user_id"]:
        raise Forbidden()
    if visibility not in ("public", "private"):
        visibility = "public"
    title = title.strip()
    if not title:
        return RedirectResponse(url=f"/videos/{video.id}/edit?error=empty_title", status_code=303)
    video.title = title
    video.description = description.strip() or None
    video.category_id = category_id.strip() or None
    video.visibility = visibility
    video.updated_at = int(time.time())
    db.commit()
    return RedirectResponse(url=f"/videos/{video.id}/edit", status_code=303)


@app.post("/api/videos/{video_id}/delete")
async def api_video_delete(
    request: Request,
    video_id: str,
    db: Session = Depends(get_db),
):
    """動画を削除する（オーナーまたは Admin のみ）。HLS も削除する。"""
    if not _is_valid_id(video_id):
        return JSONResponse({"error": "invalid video_id"}, status_code=400)
    current_user = require_login(request)
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return JSONResponse({"error": "video not found"}, status_code=404)
    if "admin" not in current_user["roles"] and video.owner_user_id != current_user["user_id"]:
        raise Forbidden()
    # MinIO から HLS を削除する
    _delete_hls_from_minio(video.id)
    # MinIO からサムネイルを削除する
    _delete_thumbnails_from_minio(video.id, db)
    # input.mp4 が残っている場合はローカルからも削除する
    local_dir = os.path.join(VIDEOS_DIR, video.id)
    if os.path.exists(local_dir):
        shutil.rmtree(local_dir, ignore_errors=True)
    # VideoPermission を削除する
    db.query(VideoPermission).filter(VideoPermission.video_id == video.id).delete()
    # Thumbnail を削除する
    db.query(Thumbnail).filter(Thumbnail.video_id == video.id).delete()
    # Job を削除する
    db.query(Job).filter(Job.video_id == video.id).delete()
    # Video を削除する
    db.delete(video)
    db.commit()
    return RedirectResponse(url="/upload", status_code=303)


@app.post("/api/videos/{video_id}/replace")
async def api_video_replace(
    request: Request,
    video_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """動画ファイルを差し替える（video_id は変わらない）。HLS を再生成する。"""
    if not _is_valid_id(video_id):
        return JSONResponse({"error": "invalid video_id"}, status_code=400)
    current_user = require_login(request)
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return JSONResponse({"error": "video not found"}, status_code=404)
    if "admin" not in current_user["roles"] and video.owner_user_id != current_user["user_id"]:
        raise Forbidden()
    now = int(time.time())
    # 古い HLS を MinIO から削除する
    _delete_hls_from_minio(video.id)
    # 古いサムネイルを MinIO と DB から削除する
    _delete_thumbnails_from_minio(video.id, db)
    db.query(Thumbnail).filter(Thumbnail.video_id == video.id).delete()
    db.commit()
    # 新しい input.mp4 を保存する
    output_dir = os.path.join(VIDEOS_DIR, video.id)
    os.makedirs(output_dir, exist_ok=True)
    input_path = os.path.join(output_dir, "input.mp4")
    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    # 既存の split ジョブを再利用（ステータスをリセット）またはレコードを作成する
    job = db.query(Job).filter(Job.video_id == video.id, Job.type == "split").first()
    if job:
        job.status = "queued"
        job.error_message = None
        job.updated_at = now
    else:
        job = Job(
            id=generate_base62_id(),
            video_id=video.id,
            type="split",
            status="queued",
            error_message=None,
            created_at=now,
            updated_at=now,
        )
        db.add(job)
    video.status = "processing"
    video.updated_at = now
    db.commit()
    redis_client.rpush(SPLIT_QUEUE, job.id)
    return RedirectResponse(url=f"/videos/{video.id}/edit", status_code=303)


# ==============================================================
# Nginx キャッシュ削除ユーティリティ
# ==============================================================

# Nginx キャッシュディレクトリ（nginx コンテナと共有ボリューム経由でアクセス）
NGINX_CACHE_DIR = os.environ.get("NGINX_CACHE_DIR", "/tmp/nginx/hls_cache")


def _get_nginx_cache_path(uri: str) -> str:
    """
    URI に対応する Nginx キャッシュファイルのパスを返す。

    Nginx の proxy_cache_key "$uri" と levels=1:2 に従ってパスを構築する。

    Args:
        uri: キャッシュキーとなる URI パス（例: /videos/{id}/segment000.ts）

    Returns:
        キャッシュファイルの絶対パス
    """
    # Nginx の proxy_cache が内部で行う処理と同一のアルゴリズムでキャッシュパスを逆算する。
    # 暗号学的な安全性ではなく、キャッシュファイルパスの再現のみを目的とした MD5 使用。
    md5 = hashlib.md5(uri.encode()).hexdigest()  # noqa: S324
    return os.path.join(NGINX_CACHE_DIR, md5[-1], md5[-3:-1], md5)


def _delete_nginx_cache_for_video(video_id: str) -> int:
    """
    MinIO から HLS ファイル一覧を取得し、対応する Nginx キャッシュファイルを削除する。

    Args:
        video_id: 動画の UUID

    Returns:
        削除したキャッシュファイルの数
    """
    bucket = os.environ.get("MINIO_BUCKET", "minitube")
    s3 = _get_s3_client()
    prefix = f"hls/{video_id}/"
    deleted = 0

    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                # MinIO キー: hls/{video_id}/segment000.ts
                # → URI: /videos/{video_id}/segment000.ts
                key = obj["Key"]
                filename = key[len(prefix):]
                uri = f"/{bucket}/hls/{video_id}/{filename}"
                path = _get_nginx_cache_path(uri)
                if os.path.exists(path):
                    try:
                        os.remove(path)
                        logger.info("Nginx キャッシュ削除: uri=%s", uri)
                        deleted += 1
                    except OSError as e:
                        logger.warning("Nginx キャッシュ削除失敗: uri=%s error=%s", uri, e)
    except ClientError as e:
        logger.warning("MinIO からの HLS ファイル一覧取得に失敗しました: %s", e)

    logger.info("Nginx キャッシュ削除完了: video_id=%s, 削除数=%d", video_id, deleted)
    return deleted


@app.post("/api/videos/{video_id}/clear_cache")
async def api_video_clear_cache(
    request: Request,
    video_id: str,
    db: Session = Depends(get_db),
):
    """
    指定した動画の Nginx HLS キャッシュを削除する（オーナーまたは Admin のみ）。

    MinIO から HLS ファイル一覧を取得し、対応するキャッシュファイルをすべて削除する。
    削除後は次回アクセス時に新しい HLS が配信される。
    """
    if not _is_valid_id(video_id):
        return JSONResponse({"error": "invalid video_id"}, status_code=400)
    current_user = require_login(request)
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return JSONResponse({"error": "video not found"}, status_code=404)
    if "admin" not in current_user["roles"] and video.owner_user_id != current_user["user_id"]:
        raise Forbidden()
    deleted = _delete_nginx_cache_for_video(video.id)
    logger.info("Nginx キャッシュ削除 API: video_id=%s, 削除数=%d", video_id, deleted)
    return RedirectResponse(url=f"/videos/{video.id}/edit?cache_cleared={deleted}", status_code=303)



# ==============================================================
# 視聴履歴エンドポイント
# ==============================================================

@app.post("/api/videos/{video_id}/watch")
async def api_watch_start(
    video_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """再生開始時に視聴履歴を作成または更新する（ログイン必須）。"""
    if not _is_valid_id(video_id):
        return JSONResponse({"error": "invalid video_id"}, status_code=400)
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return JSONResponse({"error": "video not found"}, status_code=404)
    if not can_view_video(video, user, db):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    now = int(time.time())
    history = db.query(WatchHistory).filter(
        WatchHistory.user_id == user["user_id"],
        WatchHistory.video_id == video_id,
    ).first()
    if history:
        history.last_watched_at = now
    else:
        history = WatchHistory(
            user_id=user["user_id"],
            video_id=video_id,
            last_watched_at=now,
            last_position=0,
            duration=None,
            completed=False,
        )
        db.add(history)
    db.commit()
    return JSONResponse({"ok": True})


@app.post("/api/videos/{video_id}/progress")
async def api_watch_progress(
    video_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """再生位置・動画長を更新する（ログイン必須）。JSON body: {position: int, duration: int}"""
    if not _is_valid_id(video_id):
        return JSONResponse({"error": "invalid video_id"}, status_code=400)
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    try:
        position = int(body.get("position", 0))
    except (TypeError, ValueError):
        return JSONResponse({"error": "invalid position value"}, status_code=400)
    raw_duration = body.get("duration")
    try:
        duration = int(raw_duration) if raw_duration is not None else None
    except (TypeError, ValueError):
        return JSONResponse({"error": "invalid duration value"}, status_code=400)
    history = db.query(WatchHistory).filter(
        WatchHistory.user_id == user["user_id"],
        WatchHistory.video_id == video_id,
    ).first()
    if not history:
        return JSONResponse({"error": "watch history not found"}, status_code=404)
    history.last_position = position
    if duration is not None and history.duration is None:
        history.duration = duration
    db.commit()
    return JSONResponse({"ok": True})


@app.post("/api/videos/{video_id}/complete")
async def api_watch_complete(
    video_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """視聴完了を記録する（ログイン必須）。"""
    if not _is_valid_id(video_id):
        return JSONResponse({"error": "invalid video_id"}, status_code=400)
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    history = db.query(WatchHistory).filter(
        WatchHistory.user_id == user["user_id"],
        WatchHistory.video_id == video_id,
    ).first()
    if not history:
        return JSONResponse({"error": "watch history not found"}, status_code=404)
    history.completed = True
    db.commit()
    return JSONResponse({"ok": True})


@app.get("/api/users/me/history")
async def api_user_history(
    request: Request,
    db: Session = Depends(get_db),
):
    """最近見た動画一覧を返す（ログイン必須、last_watched_at の降順）。"""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    rows = (
        db.query(WatchHistory, Video)
        .join(Video, WatchHistory.video_id == Video.id)
        .filter(WatchHistory.user_id == user["user_id"])
        .order_by(WatchHistory.last_watched_at.desc())
        .all()
    )
    result = []
    for h, v in rows:
        result.append({
            "video_id": h.video_id,
            "title": v.title,
            "last_watched_at": h.last_watched_at,
            "last_position": h.last_position,
            "duration": h.duration,
            "completed": h.completed,
        })
    return JSONResponse({"history": result})


@app.get("/api/users/me/resume")
async def api_user_resume(
    request: Request,
    db: Session = Depends(get_db),
):
    """続きから再生できる動画一覧を返す（ログイン必須、last_position > 0）。"""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    rows = (
        db.query(WatchHistory, Video)
        .join(Video, WatchHistory.video_id == Video.id)
        .filter(
            WatchHistory.user_id == user["user_id"],
            WatchHistory.last_position > 0,
        )
        .order_by(WatchHistory.last_watched_at.desc())
        .all()
    )
    result = []
    for h, v in rows:
        result.append({
            "video_id": h.video_id,
            "title": v.title,
            "last_watched_at": h.last_watched_at,
            "last_position": h.last_position,
            "duration": h.duration,
            "completed": h.completed,
        })
    return JSONResponse({"resume": result})


# ==============================================================
# サムネイル管理エンドポイント
# ==============================================================

@app.post("/api/videos/{video_id}/thumbnails/{thumbnail_id}/activate")
async def api_thumbnail_activate(
    request: Request,
    video_id: str,
    thumbnail_id: str,
    db: Session = Depends(get_db),
):
    """
    指定したサムネイルを active にする（オーナーまたは Admin のみ）。

    同じ video_id の既存 active サムネイルを false にしてから、
    指定サムネイルを active=true に設定する。
    """
    if not _is_valid_id(video_id) or not _is_valid_id(thumbnail_id):
        return JSONResponse({"error": "invalid id"}, status_code=400)
    current_user = require_login(request)
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return JSONResponse({"error": "video not found"}, status_code=404)
    if "admin" not in current_user["roles"] and video.owner_user_id != current_user["user_id"]:
        raise Forbidden()
    thumbnail = db.query(Thumbnail).filter(
        Thumbnail.id == thumbnail_id, Thumbnail.video_id == video_id
    ).first()
    if not thumbnail:
        return JSONResponse({"error": "thumbnail not found"}, status_code=404)
    # 既存の active を全て false にする
    db.query(Thumbnail).filter(Thumbnail.video_id == video_id).update({"active": False})
    thumbnail.active = True
    db.commit()
    return RedirectResponse(url=f"/videos/{video_id}/edit", status_code=303)
