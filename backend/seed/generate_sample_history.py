"""가상의 과거 개찰 결과 샘플(sample_history.csv)을 만든다.

실제 입찰과 관계없는 무작위 데이터이며, 화면·분석 기능 시험용이다. 난수 시드를 고정해 항상 같은 파일이 나온다.
    python seed/generate_sample_history.py
"""

import csv
import random
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

OUT = Path(__file__).with_name("sample_history.csv")
AGENCIES = ["샘플시청", "샘플군청", "샘플교육청", "샘플도청"]
INDUSTRIES = ["토목공사업", "전기공사업", "정보통신공사업", "소방시설공사업", "실내건축공사업"]
REGIONS = ["샘플도", "가상도"]
AWARD = ["적격심사", "적격심사", "적격심사", "최저가"]


def main() -> None:
    rng = random.Random(20261027)
    rows = []
    start = date(2023, 11, 1)
    for i in range(240):
        ann = start + timedelta(days=rng.randrange(0, 1055))
        opening = datetime.combine(ann + timedelta(days=rng.randrange(10, 20)), datetime.min.time()).replace(hour=rng.choice([10, 11, 14]))
        base = Decimal(rng.randrange(30, 3000)) * 1_000_000 + Decimal(rng.randrange(0, 1000)) * 1000
        authority = "지방자치단체" if rng.random() < 0.75 else "국가기관"
        award = rng.choice(AWARD)
        has_result = rng.random() < 0.92
        row = {
            "공고번호": f"SAMPLE-H{i:04d}", "차수": "000", "공고명": f"[샘플] 가상 공사 {i:04d}",
            "발주기관": rng.choice(AGENCIES), "기관유형": authority, "업무구분": "공사", "계약방법": "제한경쟁",
            "낙찰방법": award, "지역": rng.choice(REGIONS), "업종": rng.choice(INDUSTRIES),
            "공고일": ann.isoformat(), "개찰일시": opening.strftime("%Y-%m-%d %H:%M"), "기초금액": str(base),
            "예정가격": "", "참가업체수": "", "낙찰업체": "", "낙찰금액": "", "낙찰률": "",
        }
        if has_result:
            mu = -0.15 if authority == "지방자치단체" else 0.05
            s = max(min(rng.gauss(mu, 0.9), 3.0), -3.0)
            est = (base * (1 + Decimal(str(round(s, 4))) / 100)).quantize(Decimal(1), ROUND_DOWN)
            rate = Decimal(str(round(rng.uniform(87.75, 88.6) if award == "적격심사" else rng.uniform(80.0, 86.0), 3)))
            amt = (est * rate / 100).quantize(Decimal(1), ROUND_DOWN)
            row.update({
                "예정가격": str(est), "참가업체수": str(rng.randrange(20, 450)), "낙찰업체": f"가상업체{rng.randrange(1, 60):02d}",
                "낙찰금액": str(amt), "낙찰률": str((amt / est * 100).quantize(Decimal("0.001"))),
            })
        rows.append(row)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{OUT} ({len(rows)}행)")


if __name__ == "__main__":
    main()
