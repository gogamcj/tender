"""실행 중인 서버에 가상 샘플 데이터(과거 개찰 결과 240건, 예시 규칙)를 올린다.

사용법:
    BID_API_URL=http://127.0.0.1:8000 BID_USERNAME=admin python scripts/load_sample_data.py
비밀번호는 BID_PASSWORD 환경변수나 입력 프롬프트로 받는다(명령줄 인자로 받지 않음).
샘플은 실제 입찰과 무관한 가상 데이터다. 운영 DB 에는 올리지 마세요.
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

import httpx

SEED = Path(__file__).resolve().parents[1] / "backend" / "seed"
EXAMPLE_RULE = {
    "rule_code": "SAMPLE_LOWER_LIMIT",
    "rule_name": "샘플용 낙찰하한율 규칙(가상, 미검증)",
    "procurement_type": "construction",
    "effective_from": "2020-01-01",
    "formula_definition": {"module": "simple_lower_limit", "params": {"lower_limit_rate_pct": "87.745"}},
    "rounding_rule": {"mode": "ceil", "unit": 1},
    "notes": "샘플 데이터 시험용. 실제 규정과 대조하지 않았습니다.",
}


def main() -> int:
    base = os.environ.get("BID_API_URL", "http://127.0.0.1:8000")
    username = os.environ.get("BID_USERNAME", "admin")
    password = os.environ.get("BID_PASSWORD") or getpass.getpass(f"{username} 비밀번호: ")
    with httpx.Client(base_url=base, timeout=120) as c:
        r = c.post("/api/auth/login", json={"username": username, "password": password})
        if r.status_code != 200:
            print("로그인 실패:", r.text, file=sys.stderr)
            return 1
        up = c.post("/api/imports", files={"file": ("sample_history.csv", (SEED / "sample_history.csv").read_bytes(), "text/csv")}).json()
        if up.get("previously_imported_job_ids"):
            print("이미 올린 적이 있는 파일입니다. 건너뜁니다(작업", up["previously_imported_job_ids"], ").")
        else:
            pv = c.post(f"/api/imports/{up['job_id']}/preview", json={
                "mapping": up["sheets"][0]["suggested_mapping"], "options": {"default_winning_rate_basis": "estimated_price"}}).json()
            print("미리보기:", pv["counts"])
            cm = c.post(f"/api/imports/{up['job_id']}/commit", json={}).json()
            print("저장:", cm["counts"])
        r = c.post("/api/rules", json=EXAMPLE_RULE)
        print("예시 규칙:", "등록" if r.status_code == 201 else f"건너뜀({r.status_code})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
