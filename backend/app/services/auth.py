"""사용자·로그인 세션."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    DUMMY_HASH,
    check_password_policy,
    hash_password,
    needs_rehash,
    new_token,
    token_hash,
    verify_password,
)
from app.db.enums import UserRole
from app.db.models import AppEvent, User, UserSession


class LoginLocked(RuntimeError):
    pass


def create_user(session: Session, username: str, password: str, role: UserRole) -> User:
    username = username.strip()
    if not username or len(username) > 64:
        raise ValueError("사용자 이름은 1~64자여야 합니다.")
    check_password_policy(password, username)
    user = User(username=username, password_hash=hash_password(password), role=role, is_active=True)
    session.add(user)
    session.flush()
    _event(session, "info", "user_created", {"username": username, "role": role.value})
    return user


def set_password(session: Session, user: User, password: str) -> None:
    check_password_policy(password, user.username)
    user.password_hash = hash_password(password)
    revoke_all(session, user)  # 비밀번호를 바꾸면 기존 세션을 모두 끊는다


def _event(session: Session, level: str, category: str, context: dict) -> None:
    session.add(AppEvent(level=level, category=category, message=category, context=context))


def _recent_failures(session: Session, username: str) -> int:
    s = get_settings()
    since = datetime.now(UTC) - timedelta(minutes=s.login_lockout_minutes)
    events = session.scalars(
        select(AppEvent).where(AppEvent.category.in_(("login_failed", "login_ok")), AppEvent.created_at >= since)
        .order_by(AppEvent.id.desc())
    )
    count = 0
    for e in events:
        if (e.context or {}).get("username") != username:
            continue
        if e.category == "login_ok":
            break
        count += 1
    return count


def authenticate(session: Session, username: str, password: str) -> User | None:
    s = get_settings()
    if _recent_failures(session, username) >= s.login_max_failures:
        raise LoginLocked(f"로그인 실패가 잦아 {s.login_lockout_minutes}분 동안 로그인할 수 없습니다.")
    user = session.scalar(select(User).where(User.username == username))
    ok = verify_password(user.password_hash if user else DUMMY_HASH, password)
    if not (user and ok and user.is_active):
        _event(session, "warning", "login_failed", {"username": username})
        session.commit()
        return None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    _event(session, "info", "login_ok", {"username": username})
    return user


def create_session(session: Session, user: User) -> tuple[str, datetime]:
    token = new_token()
    expires = datetime.now(UTC) + timedelta(hours=get_settings().session_hours)
    session.add(UserSession(user_id=user.id, token_hash=token_hash(token), expires_at=expires, revoked=False))
    session.flush()
    return token, expires


def resolve(session: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = session.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
    if row is None or row.revoked or row.expires_at <= datetime.now(UTC):
        return None
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    return user


def revoke(session: Session, token: str) -> None:
    row = session.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
    if row is not None:
        row.revoked = True


def revoke_all(session: Session, user: User) -> None:
    for row in session.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked.is_(False))):
        row.revoked = True


def user_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(User)) or 0
