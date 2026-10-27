"""collection fields

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27 03:24:48.708788

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db.base


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_LOOKUP = ("found", "not_queried", "out_of_period", "out_of_scope", "confirmed_absent", "source_error")
NEW_LOOKUP = ("found", "not_queried", "out_of_period", "out_of_scope", "not_returned", "confirmed_absent", "source_error")


def _lookup_check(values: tuple[str, ...]) -> str:
    return "lookup_status IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    """수집 관련 컬럼 추가, 조회 상태에 '응답 없음(not_returned)' 추가."""
    with op.batch_alter_table("bid_results", schema=None) as batch_op:
        batch_op.add_column(sa.Column("winning_vendor_id", sa.String(length=40), nullable=True))
        batch_op.drop_constraint(batch_op.f("ck_bid_results_lookup_status"), type_="check")
        batch_op.create_check_constraint("lookup_status", _lookup_check(NEW_LOOKUP))
    with op.batch_alter_table("procurement_notices", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reserve_range_begin_rate", app.db.base.ExactDecimal(precision=12, scale=6), nullable=True))
        batch_op.add_column(sa.Column("reserve_range_end_rate", app.db.base.ExactDecimal(precision=12, scale=6), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("procurement_notices", schema=None) as batch_op:
        batch_op.drop_column("reserve_range_end_rate")
        batch_op.drop_column("reserve_range_begin_rate")
    op.execute("UPDATE bid_results SET lookup_status = 'not_queried' WHERE lookup_status = 'not_returned'")
    with op.batch_alter_table("bid_results", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_bid_results_lookup_status"), type_="check")
        batch_op.create_check_constraint("lookup_status", _lookup_check(OLD_LOOKUP))
        batch_op.drop_column("winning_vendor_id")
