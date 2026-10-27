import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

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


@pytest.fixture
def client(engine):
    from fastapi.testclient import TestClient

    from app.db.session import get_session
    from app.main import create_app

    app = create_app()
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def _override() -> Iterator[Session]:
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        yield c
