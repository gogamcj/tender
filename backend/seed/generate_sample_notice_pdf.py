"""가상 공고문 PDF(seed/sample_notice.pdf) 생성. 실제 공고가 아니다.

실행: cd backend && python seed/generate_sample_notice_pdf.py  (개발 의존성 reportlab 필요)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.pdf_samples import sample_notice_pdf  # noqa: E402

if __name__ == "__main__":
    out = ROOT / "seed" / "sample_notice.pdf"
    out.write_bytes(sample_notice_pdf())
    print(out)
