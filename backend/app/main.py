from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.api import analysis, calc, collections, imports, notices, rules
from app.core.config import get_settings
from app.engines.calc import CalcInputError
from app.engines.rules import RuleBlockedError


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="공공입찰 분석·의사결정 지원 API. 낙찰을 보장하지 않으며, 실제 투찰을 수행하지 않습니다.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
    )

    @app.exception_handler(CalcInputError)
    async def _calc_error(_: Request, exc: CalcInputError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "calc_input", "field": exc.field, "message": exc.message})

    @app.exception_handler(RuleBlockedError)
    async def _blocked(_: Request, exc: RuleBlockedError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": "rule_blocked", "message": str(exc)})

    @app.exception_handler(ValidationError)
    async def _validation(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "validation", "detail": exc.errors(include_url=False, include_context=False, include_input=False)})

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        # 유일성·외래키 위반: 기존 데이터를 덮어쓰지 않고 거부한다.
        return JSONResponse(status_code=409, content={"error": "conflict", "message": "중복되었거나 참조 관계를 위반하는 데이터입니다."})

    @app.get("/api/health", tags=["시스템"])
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(calc.router)
    app.include_router(rules.router)
    app.include_router(imports.router)
    app.include_router(collections.router)
    app.include_router(notices.router)
    app.include_router(analysis.router)
    return app


app = create_app()
