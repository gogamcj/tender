"""비밀번호 해시(Argon2id)와 세션 토큰."""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # Argon2id, 라이브러리 기본 비용 인자

MIN_PASSWORD_LENGTH = 10


class WeakPassword(ValueError):
    pass


def check_password_policy(password: str, username: str | None = None) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword(f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다.")
    if username and username.lower() in password.lower():
        raise WeakPassword("비밀번호에 사용자 이름을 넣을 수 없습니다.")
    if password.isdigit() or password.isalpha():
        raise WeakPassword("비밀번호는 문자와 숫자·기호를 섞어야 합니다.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# 사용자가 없을 때도 같은 시간이 걸리도록 비교에 쓰는 더미 해시
DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
