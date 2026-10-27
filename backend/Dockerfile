# 백엔드(FastAPI) 이미지. 시작할 때 DB 마이그레이션을 적용한 뒤 서버를 띄운다.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# 의존성 먼저 설치(소스만 바뀌면 이 층은 다시 만들지 않음)
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py && pip install . && rm -rf app build *.egg-info

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY seed ./seed
RUN pip install --no-deps . \
    && useradd --system --uid 10001 --home /app bid \
    && mkdir -p /data/storage && chown bid /data/storage

USER bid
ENV BID_STORAGE_DIR=/data/storage
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
