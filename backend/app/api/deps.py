"""인증·권한 의존성.

- 모든 /api 경로는 로그인이 필요하다(/api/health, /api/auth/login 제외).
- 조회(GET·HEAD)는 모든 역할, 변경(POST·PUT·PATCH·DELETE)은 user·admin 만 가능하다.
- 관리자 전용 기능과 원가(민감 자료) 접근은 각 경로에서 추가로 검사한다.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.enums import UserRole
from app.db.models import User
from app.db.session import get_session
from app.services import auth as auth_service

COOKIE_NAME = "bid_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def session_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(COOKIE_NAME)


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    user = auth_service.resolve(session, session_token(request))
    if user is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    request.state.user = user
    return user


def require_access(request: Request, user: User = Depends(current_user)) -> User:
    if request.method not in SAFE_METHODS and user.role is UserRole.VIEWER:
        raise HTTPException(403, "조회 전용 계정은 자료를 바꿀 수 없습니다.")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role is not UserRole.ADMIN:
        raise HTTPException(403, "관리자만 사용할 수 있습니다.")
    return user


def can_read_cost(user: User, owner_user_id: int | None) -> bool:
    """원가 자료: 관리자 또는 작성자만. 조회 전용 계정은 볼 수 없다."""
    if user.role is UserRole.ADMIN:
        return True
    return user.role is UserRole.USER and owner_user_id == user.id
