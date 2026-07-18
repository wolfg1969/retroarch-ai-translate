import { useEffect, useState, useRef } from "react";

/**
 * Generic hook that calls an async function on a timer.
 *
 * Returns ``{ data, error, loading }`` — *data* holds the last successful
 * result (preserved across re-renders while loading).
 */
export function usePolling<T>(
  fn: () => Promise<T>,
  intervalMs: number,
  deps: unknown[] = []
): { data: T | null; error: string | null; loading: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;

    const tick = async () => {
      try {
        const result = await fn();
        if (mounted.current) {
          setData(result);
          setError(null);
          setLoading(false);
        }
      } catch (e) {
        if (mounted.current) {
          setError(String(e));
          setLoading(false);
        }
      }
    };

    // Initial fetch
    tick();

    // Periodic
    const timer = setInterval(tick, intervalMs);

    return () => {
      mounted.current = false;
      clearInterval(timer);
    };
  }, [intervalMs, ...deps]);

  return { data, error, loading };
}
