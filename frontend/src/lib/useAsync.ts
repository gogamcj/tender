import { useCallback, useEffect, useRef, useState } from "react";

export interface AsyncState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
  setData: (d: T | null) => void;
}

/** 의존값이 바뀌면 다시 불러온다. 나중에 시작한 요청의 결과만 반영한다. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], enabled = true): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [tick, setTick] = useState(0);
  const seq = useRef(0);
  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const my = ++seq.current;
    setLoading(true);
    setError(null);
    fn().then(
      (d) => my === seq.current && (setData(d), setLoading(false)),
      (e: Error) => my === seq.current && (setError(e), setLoading(false)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, enabled]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}

/** 버튼으로 실행하는 작업(저장·계산 등). */
export function useAction<A extends unknown[], T>(fn: (...a: A) => Promise<T>) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [result, setResult] = useState<T | null>(null);
  const run = useCallback(
    async (...a: A) => {
      setRunning(true);
      setError(null);
      try {
        const r = await fn(...a);
        setResult(r);
        return r;
      } catch (e) {
        setError(e as Error);
        return null;
      } finally {
        setRunning(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fn],
  );
  return { run, running, error, result, setResult };
}
