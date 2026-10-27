"""계산 규칙의 정의 형식.

규칙은 코드에 하드코딩하지 않고 데이터(bid_rules 테이블 또는 시드 JSON)로 관리한다.
formula_definition 은 "어떤 산식 모듈을 어떤 파라미터로 쓰는가"만 담고,
실제 계산은 engines.calc 의 순수 함수가 수행한다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ANY = "any"


class ProcurementCategory(StrEnum):
    CONSTRUCTION = "construction"  # 공사
    SERVICE = "service"  # 용역
    GOODS = "goods"  # 물품
    FOREIGN = "foreign"  # 외자
    OTHER = "other"


class AuthorityType(StrEnum):
    NATIONAL = "national"  # 국가기관
    LOCAL = "local"  # 지방자치단체
    PUBLIC_CORP = "public_corp"  # 공기업·준정부기관
    OTHER = "other"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"  # 원문 규정과 대조 확인
    UNVERIFIED = "unverified"  # 미검증
    RETIRED = "retired"  # 폐지·사용 중지


class AmountBasis(StrEnum):
    PRESUMED_PRICE = "presumed_price"  # 추정가격
    BASE_AMOUNT = "base_amount"  # 기초금액
    ESTIMATED_PRICE = "estimated_price"  # 예정가격


class Applicability(BaseModel):
    """규칙이 적용되는 금액 구간 등 추가 조건."""

    model_config = ConfigDict(extra="forbid")

    amount_basis: AmountBasis | None = None
    amount_min: Decimal | None = Field(default=None, description="이상(포함)")
    amount_max_exclusive: Decimal | None = Field(default=None, description="미만(제외)")
    region_codes: list[str] | None = None
    industry_codes: list[str] | None = None

    @model_validator(mode="after")
    def _check(self) -> Applicability:
        if (self.amount_min is not None or self.amount_max_exclusive is not None) and self.amount_basis is None:
            raise ValueError("금액 구간을 쓰려면 amount_basis(기준 금액 종류)를 지정해야 합니다.")
        if self.amount_min is not None and self.amount_max_exclusive is not None and self.amount_min >= self.amount_max_exclusive:
            raise ValueError("amount_min 은 amount_max_exclusive 보다 작아야 합니다.")
        return self


class FormulaDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: str
    params: dict[str, Any] = Field(default_factory=dict)


class RoundingDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    unit: int = 1
    source: str | None = None


class RuleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_code: str
    rule_name: str
    procurement_type: str = ANY
    issuing_authority_type: str = ANY
    contract_method: str = ANY
    award_method: str = ANY
    effective_from: date
    effective_until: date | None = Field(default=None, description="이 날짜까지 적용(포함). None 이면 현재 유효")
    source_document: str | None = None
    source_url: str | None = None
    source_version: str = "1"
    formula_definition: FormulaDefinition
    rounding_rule: RoundingDefinition | None = None
    applicability: Applicability = Field(default_factory=Applicability)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    verified_at: date | None = None
    notes: str | None = None

    @field_validator("procurement_type")
    @classmethod
    def _proc(cls, v: str) -> str:
        if v != ANY:
            ProcurementCategory(v)
        return v

    @field_validator("issuing_authority_type")
    @classmethod
    def _auth(cls, v: str) -> str:
        if v != ANY:
            AuthorityType(v)
        return v

    @model_validator(mode="after")
    def _dates(self) -> RuleDefinition:
        if self.effective_until is not None and self.effective_until < self.effective_from:
            raise ValueError("effective_until 이 effective_from 보다 앞설 수 없습니다.")
        if self.verification_status is VerificationStatus.VERIFIED and not (self.source_document or self.source_url):
            raise ValueError("검증됨 상태의 규칙은 근거 문서(source_document 또는 source_url)가 있어야 합니다.")
        return self


class NoticeContext(BaseModel):
    """규칙 선택에 필요한 공고 조건."""

    announcement_date: date | None
    procurement_type: str | None = None
    issuing_authority_type: str | None = None
    contract_method: str | None = None
    award_method: str | None = None
    presumed_price: Decimal | None = None
    base_amount: Decimal | None = None
    estimated_price: Decimal | None = None
    region_code: str | None = None
    industry_code: str | None = None

    def amount_for(self, basis: AmountBasis) -> Decimal | None:
        return {
            AmountBasis.PRESUMED_PRICE: self.presumed_price,
            AmountBasis.BASE_AMOUNT: self.base_amount,
            AmountBasis.ESTIMATED_PRICE: self.estimated_price,
        }[basis]
