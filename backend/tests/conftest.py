import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.db.session import make_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]


def migrate(url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.cmd_opts = type("o", (), {"x": [f"db_url={url}"]})()
    command.upgrade(cfg, "head")


@pytest.fixture(params=["sqlite", "postgresql"])
def engine(request, tmp_path_factory) -> Iterator[Engine]:
    if request.param == "sqlite":
        url = f"sqlite:///{tmp_path_factory.mktemp('db') / 'test.db'}"
    else:
        url = os.environ.get("BID_TEST_PG_URL")
        if not url:
            pytest.skip("BID_TEST_PG_URL 미설정: PostgreSQL 테스트 생략")
        _reset_pg(url)
    migrate(url)
    eng = make_engine(url)
    yield eng
    eng.dispose()


def _reset_pg(url: str) -> None:
    from sqlalchemy import text

    eng = make_engine(url)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    eng.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


TEST_PASSWORD = "test-pass-2026!"


@pytest.fixture
def make_client(engine):
    """역할별로 로그인된 TestClient 를 만든다. make_client("user", "kim")"""
    from contextlib import ExitStack

    from fastapi.testclient import TestClient

    from app.db.enums import UserRole
    from app.db.session import get_session
    from app.main import create_app
    from app.services.auth import create_user

    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def _override() -> Iterator[Session]:
        with factory() as s:
            yield s

    stack = ExitStack()

    def make(role: str = "admin", username: str | None = None, *, login: bool = True):
        app = create_app()
        app.dependency_overrides[get_session] = _override
        c = stack.enter_context(TestClient(app))
        if login:
            name = username or f"{role}-user"
            with factory() as s:
                from sqlalchemy import select

                from app.db.models import User

                if s.scalar(select(User).where(User.username == name)) is None:
                    create_user(s, name, TEST_PASSWORD, UserRole(role))
                    s.commit()
            r = c.post("/api/auth/login", json={"username": name, "password": TEST_PASSWORD})
            assert r.status_code == 200, r.text
        return c

    yield make
    stack.close()


@pytest.fixture
def client(make_client):
    return make_client("admin")


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    """테스트마다 업로드 저장 위치를 임시 폴더로 분리한다."""
    from app.core.config import get_settings

    monkeypatch.setenv("BID_STORAGE_DIR", str(tmp_path / "storage"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
