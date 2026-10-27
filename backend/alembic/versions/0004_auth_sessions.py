"""auth sessions and viewer role

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db.base


revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _role_check(values: tuple[str, ...]) -> str:
    return "role IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    """로그인 세션 테이블, 조회 전용 역할(viewer) 추가."""
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", app.db.base.UTCDateTime(), nullable=False),
        sa.Column("expires_at", app.db.base.UTCDateTime(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_sessions_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_user_sessions_token_hash")),
    )
    with op.batch_alter_table("user_sessions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_sessions_user_id"), ["user_id"], unique=False)
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_users_user_role"), type_="check")
        batch_op.create_check_constraint("user_role", _role_check(("admin", "user", "viewer")))


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'user' WHERE role = 'viewer'")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_users_user_role"), type_="check")
        batch_op.create_check_constraint("user_role", _role_check(("admin", "user")))
    with op.batch_alter_table("user_sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_sessions_user_id"))
    op.drop_table("user_sessions")
