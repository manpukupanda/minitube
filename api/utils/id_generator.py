"""
Base62 ID ジェネレータ

64bit のランダム整数を Base62（0-9A-Za-z）でエンコードし、11 文字固定の
URL-safe な ID 文字列を生成する。暗号学的に安全な `secrets` モジュールを使用する。
"""

import secrets
import string

# Base62 アルファベット（0-9, A-Z, a-z の順）
ALPHABET = string.digits + string.ascii_uppercase + string.ascii_lowercase  # 62 chars
_BASE = len(ALPHABET)
_ID_LENGTH = 11


def generate_base62_id() -> str:
    """64bit ランダム値を Base62 エンコードした 11 文字固定の ID を返す。"""
    value = secrets.randbits(64)
    chars: list[str] = []

    while value > 0:
        value, rem = divmod(value, _BASE)
        chars.append(ALPHABET[rem])

    return "".join(reversed(chars)).rjust(_ID_LENGTH, ALPHABET[0])
