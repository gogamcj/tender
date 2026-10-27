"""로그인·로그아웃·사용자 관리."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import WeakPassword, verify_password
from app.db.enums import UserRole
from app.db.models import User
from app.db.session import get_session
from app.services import auth as auth_service

from .deps import COOKIE_NAME, current_user, require_admin, session_token

router = APIRouter(prefix="/api/auth", tags=["인증"])
users_router = APIRouter(prefix="/api/users", tags=["사용자 관리"], dependencies=[Depends(require_admin)])


def _user(u: User) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role.value, "is_active": u.is_active, "created_at": u.created_at.isoformat()}


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@router.post("/login", summary="로그인(세션 쿠키 발급)")
def login(body: LoginIn, response: Response, session: Session = Depends(get_session)) -> dict:
    try:
        user = auth_service.authenticate(session, body.username, body.password)
    except auth_service.LoginLocked as e:
        raise HTTPException(429, str(e)) from e
    if user is None:
        raise HTTPException(401, "사용자 이름 또는 비밀번호가 맞지 않습니다.")
    token, expires = auth_service.create_session(session, user)
    session.commit()
    s = get_settings()
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=s.cookie_secure, samesite="strict",
                        max_age=s.session_hours * 3600, path="/")
    return {"user": _user(user), "expires_at": expires.isoformat()}


@router.post("/logout", summary="로그아웃")
def logout(request: Request, response: Response, session: Session = Depends(get_session)) -> dict:
    token = session_token(request)
    if token:
        auth_service.revoke(session, token)
        session.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", summary="현재 사용자")
def me(user: User = Depends(current_user)) -> dict:
    return _user(user)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(max_length=256)


@router.post("/password", summary="내 비밀번호 변경(모든 세션 종료)")
def change_password(body: PasswordIn, response: Response, user: User = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    user = session.merge(user)
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "현재 비밀번호가 맞지 않습니다.")
    try:
        auth_service.set_password(session, user, body.new_password)
    except WeakPassword as e:
        raise HTTPException(422, str(e)) from e
    session.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True, "message": "비밀번호를 바꿨습니다. 다시 로그인하세요."}


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(max_length=256)
    role: UserRole = UserRole.USER


@users_router.get("")
def list_users(session: Session = Depends(get_session)) -> list[dict]:
    return [_user(u) for u in session.scalars(select(User).order_by(User.id))]


@users_router.post("", status_code=201)
def create_user(body: UserIn, session: Session = Depends(get_session)) -> dict:
    try:
        u = auth_service.create_user(session, body.username, body.password, body.role)
    except (WeakPassword, ValueError) as e:
        raise HTTPException(422, str(e)) from e
    session.commit()
    return _user(u)


class UserPatch(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(None, max_length=256)


@users_router.patch("/{user_id}")
def update_user(user_id: int, body: UserPatch, admin: User = Depends(require_admin), session: Session = Depends(get_session)) -> dict:
    u = session.get(User, user_id)
    if u is None:
        raise HTTPException(404, "사용자가 없습니다.")
    if u.id == admin.id and (body.is_active is False or (body.role is not None and body.role is not UserRole.ADMIN)):
        raise HTTPException(400, "자기 자신의 관리자 권한을 해제하거나 비활성화할 수 없습니다.")
    if body.role is not None:
        u.role = body.role
    if body.is_active is not None:
        u.is_active = body.is_active
        if not body.is_active:
            auth_service.revoke_all(session, u)
    if body.password is not None:
        try:
            auth_service.set_password(session, u, body.password)
        except WeakPassword as e:
            raise HTTPException(422, str(e)) from e
    session.commit()
    return _user(u)
