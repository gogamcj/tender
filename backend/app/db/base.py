"""SQLAlchemy 공통 기반: SQLite 와 PostgreSQL 양쪽에서 같은 모델을 쓴다."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum as PyEnum

from sqlalchemy import JSON, BigInteger, DateTime, Enum, MetaData, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ExactDecimal(TypeDecorator):
    """고정소수점 Decimal 컬럼.

    PostgreSQL 에서는 NUMERIC(precision, scale) 로 저장한다.
    SQLite 의 NUMERIC 은 내부적으로 REAL(이진 부동소수점)로 바뀌어 큰 금액에서 오차가 생기므로,
    SQLite 에서는 10^scale 을 곱한 정수(BIGINT)로 저장해 정확도를 지킨다.
    (SQLite 에서 SQL 로 직접 합계를 내면 스케일된 정수가 나온다. 통계는 ORM 으로 읽어 계산한다.)
    """

    impl = Numeric
    cache_ok = True

    @property
    def python_type(self) -> type:
        return Decimal

    def __init__(self, precision: int, scale: int) -> None:
        super().__init__(precision=precision, scale=scale, asdecimal=True)
        self.precision = precision
        self.scale = scale
        self._quantum = Decimal(1).scaleb(-scale)

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(BigInteger())
        return dialect.type_descriptor(Numeric(self.precision, self.scale, asdecimal=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("금액·비율 컬럼에 float 를 저장할 수 없습니다. Decimal 을 사용하세요.")
        value = Decimal(value)
        quantized = value.quantize(self._quantum, rounding=ROUND_HALF_UP)
        if quantized != value:
            # 저장 단계에서 금액을 몰래 반올림하지 않는다. 처리 규칙은 계산 엔진에서 명시적으로 적용한다.
            raise ValueError(f"소수 {self.scale}자리를 넘는 값은 저장할 수 없습니다: {value}")
        if dialect.name == "sqlite":
            scaled = int(quantized.scaleb(self.scale))
            if not -(2**63) <= scaled < 2**63:
                raise OverflowError(f"SQLite 저장 범위를 넘는 값입니다: {value}")
            return scaled
        return quantized

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "sqlite":
            return Decimal(int(value)).scaleb(-self.scale).quantize(self._quantum)
        return Decimal(value)


# 금액: 원 단위 정수. 18자리면 999경 원까지.
Money = ExactDecimal(18, 0)
# 원 미만이 생길 수 있는 중간 금액(예: 절사 규칙 미확인 시 하한금액)
PreciseMoney = ExactDecimal(20, 4)
# 비율(%): 소수 6자리. 예) 87.745000, -1.234567
Rate = ExactDecimal(12, 6)

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """시간대가 있는 일시. 항상 UTC 로 저장·반환한다.

    SQLite 는 시간대 정보를 버리므로 읽을 때 UTC 를 다시 붙인다. 시간대 없는(naive) 값은 저장하지 않는다.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    @property
    def python_type(self) -> type:
        return datetime

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("시간대 정보가 없는 일시는 저장할 수 없습니다(UTC 또는 KST 를 명시하세요).")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def TZDateTime() -> UTCDateTime:  # noqa: N802 - 타입 팩토리
    return UTCDateTime()


def enum_column(enum_cls: type[PyEnum], name: str) -> Enum:
    """DB 네이티브 ENUM 대신 VARCHAR + CHECK 제약으로 저장한다(SQLite 겸용, 값 추가 시 마이그레이션 단순)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=40,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
