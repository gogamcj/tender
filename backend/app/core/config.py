"""환경변수 기반 설정. 비밀정보는 코드에 두지 않는다."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BID_", extra="ignore")

    app_name: str = "공공입찰 분석 시스템"
    environment: str = "development"
    # 개발 기본값은 SQLite. 운영은 postgresql+psycopg://user:pass@host:5432/db
    database_url: str = "sqlite:///./bid_analyzer.db"
    secret_key: SecretStr | None = None
    data_go_kr_service_key: SecretStr | None = None
    # 미검증 규칙으로 계산 자체를 막을지 여부(기본: 계산은 하되 확정 결과로 표시하지 않음)
    block_unverified_rules: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]
    # API 별 일일 호출 한도(미지정 시 개발계정 기본값). 예: BID_API_DAILY_LIMITS='{"g2b_scsbid": 10000}'
    api_daily_limits: dict[str, int] = {}
    # 업로드 원본 파일·PDF 보관 위치
    storage_dir: str = "./storage"
    # 로그인 세션
    session_hours: int = 12
    cookie_secure: bool = False  # HTTPS 로 운영할 때 반드시 true
    login_max_failures: int = 5  # 이 횟수만큼 연속 실패하면
    login_lockout_minutes: int = 15  # 이 시간 동안 로그인 거부


@lru_cache
def get_settings() -> Settings:
    return Settings()
