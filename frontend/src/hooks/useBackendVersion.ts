import { useEffect, useState } from 'react';
import { API_BASE } from '../config';
import type { BackendVersion } from '../utils/version';

/** Asks the server which version is running, once, when the app starts. Never blocks or throws. */
export function useBackendVersion(): BackendVersion {
  const [info, setInfo] = useState<BackendVersion>({ state: 'loading', version: null, commit: null });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/health`);
        const data = await res.json().catch(() => null) as { version?: unknown; commit?: unknown } | null;
        if (cancelled) return;
        if (!res.ok || typeof data?.version !== 'string') {
          // An older server answers health without a version: reachable, but its version is unknown.
          setInfo({ state: res.ok ? 'ok' : 'unreachable', version: null, commit: null });
          return;
        }
        setInfo({ state: 'ok', version: data.version, commit: typeof data.commit === 'string' ? data.commit : null });
      } catch {
        if (!cancelled) setInfo({ state: 'unreachable', version: null, commit: null });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return info;
}
