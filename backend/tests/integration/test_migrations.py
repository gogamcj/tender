"""마이그레이션 왕복(업그레이드 → 다운그레이드 → 업그레이드)과 모델-스키마 일치 확인."""

import os

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.autogenerate import compare_metadata
from sqlalchemy import text

import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.session import make_engine
from tests.conftest import BACKEND_DIR, _reset_pg


def _cfg(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.cmd_opts = type("o", (), {"x": [f"db_url={url}"]})()
    return cfg


@pytest.fixture(params=["sqlite", "postgresql"])
def url(request, tmp_path):
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'm.db'}"
    pg = os.environ.get("BID_TEST_PG_URL")
    if not pg:
        pytest.skip("BID_TEST_PG_URL 미설정")
    _reset_pg(pg)
    return pg


def test_roundtrip_keeps_data_and_matches_models(url):
    cfg = _cfg(url)
    command.upgrade(cfg, "head")
    eng = make_engine(url)
    with eng.begin() as c:
        c.execute(text(
            "insert into procurement_notices(notice_number,notice_revision,is_latest_revision,title,estimated_price_status,phase,"
            "source_name,collected_at,last_updated_at,data_status) values ('N1','000',true,'t','unknown','pre_opening','s',"
            "'2024-01-01','2024-01-01','collected')"))
    command.downgrade(cfg, "0001")
    command.upgrade(cfg, "head")
    with eng.connect() as c:
        assert c.execute(text("select count(*) from procurement_notices")).scalar() == 1
        diff = compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata)
    eng.dispose()
    assert diff == []
