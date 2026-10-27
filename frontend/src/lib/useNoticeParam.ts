import { useSearchParams } from "react-router-dom";

/** 주소창의 ?notice=ID 를 화면 간 공유한다(공고 상세 → 시나리오 등으로 이동할 때). */
export function useNoticeParam(): [number | null, (id: number | null) => void] {
  const [sp, setSp] = useSearchParams();
  const v = sp.get("notice");
  const id = v && /^\d+$/.test(v) ? Number(v) : null;
  const set = (n: number | null) => {
    const next = new URLSearchParams(sp);
    if (n) next.set("notice", String(n));
    else next.delete("notice");
    setSp(next, { replace: true });
  };
  return [id, set];
}
