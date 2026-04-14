# 認証フロー

## Cookie セッション

minitube はメールアドレス + bcrypt パスワードによる Cookie セッション認証を使用する（itsdangerous）。

- ログイン成功時に `Set-Cookie: session=...` が発行される
- 以降のリクエストは Cookie を付与して送信される
- Cookie が存在しない場合は `/login` へリダイレクトされる

## ログインフロー図

```
ユーザ          ブラウザ         Nginx           FastAPI
  │               │               │               │
  │ アクセス       │               │               │
  │──────────────▶│               │               │
  │               │ GET /upload   │               │
  │               │──────────────▶│               │
  │               │               │ proxy /upload │
  │               │               │──────────────▶│
  │               │               │               │ Cookie なし
  │               │               │               │ → 303 /login
  │               │◀──────────────────────────────│
  │               │               │               │
  │ パスワード入力 │               │               │
  │──────────────▶│               │               │
  │               │ POST /api/login               │
  │               │──────────────▶│               │
  │               │               │ proxy /api/   │
  │               │               │──────────────▶│
  │               │               │               │ パスワード照合
  │               │               │               │ Cookie 発行
  │               │◀──────────────────────────────│
  │               │ Set-Cookie: session=...        │
  │               │ 303 → /upload │               │
  │               │               │               │
  │ (以降 Cookie 付きでリクエスト)                 │
```

## 認証 API

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/login` | ログインページ |
| POST | `/api/login` | ログイン処理（Cookie 発行） |
| GET | `/logout` | ログアウト（Cookie 削除） |
| GET | `/register` | ユーザ登録ページ |
| POST | `/api/register` | ユーザ登録（viewer ロール自動付与） |
