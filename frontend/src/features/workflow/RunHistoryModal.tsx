import { useCallback, useEffect, useState } from 'react';
import { API_BASE } from '../../config';
import { useAuth } from '../../context/AuthContext';
import { formatApiError } from '../../utils/apiError';
import type { RunDetail, RunSummary } from '../../models/runs';
import { formatRunTime } from './runUtils';

const PAGE_SIZE = 20;

interface Props {
  onReplay: (run: RunDetail) => void;
  onClose: () => void;
}

export function RunHistoryModal({ onReplay, onClose }: Props) {
  const { session } = useAuth();
  const token = session?.access_token;
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [hasMore, setHasMore] = useState(false);

  const headers = useCallback(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token],
  );

  const load = useCallback(async (offset: number) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/runs?limit=${PAGE_SIZE}&offset=${offset}`, { headers: headers() });
      const data = await res.json().catch(() => null) as { runs?: RunSummary[] } | null;
      if (!res.ok || !data?.runs) {
        setError(formatApiError(data, res.status));
        return;
      }
      const page = data.runs;
      setRuns((prev) => (offset === 0 ? page : [...prev, ...page]));
      setHasMore(page.length === PAGE_SIZE);
    } catch {
      setError('Could not reach backend. Is it running on port 8000?');
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch on open
    void load(0);
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const handleReplay = async (id: string) => {
    setBusyId(id);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/runs/${id}`, { headers: headers() });
      const data = await res.json().catch(() => null) as RunDetail | null;
      if (!res.ok || !data) {
        setError(formatApiError(data, res.status));
        return;
      }
      onReplay(data);
      onClose();
    } catch {
      setError('Could not reach backend. Is it running on port 8000?');
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (id: string) => {
    setBusyId(id);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/runs/${id}`, { method: 'DELETE', headers: headers() });
      if (!res.ok && res.status !== 404) {
        const data = await res.json().catch(() => null) as unknown;
        setError(formatApiError(data, res.status));
        return;
      }
      setRuns((prev) => prev.filter((r) => r.id !== id));
    } catch {
      setError('Could not reach backend. Is it running on port 8000?');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal run-history-modal" role="dialog" aria-label="Run history">
        <div className="modal-header">
          <span className="modal-title">Run History</span>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="modal-body">
          <p className="modal-hint">
            Your recent simulations (newest first). Replay shows a stored trace on the canvas; older runs are removed automatically.
          </p>

          {error && <div className="modal-error" role="alert">{error}</div>}

          {!loading && runs.length === 0 && !error && (
            <div className="run-history-empty">No saved runs yet. Run a simulation and it will appear here.</div>
          )}

          <ul className="run-history-list">
            {runs.map((run) => (
              <li key={run.id} className="run-history-item">
                <div className="run-history-main">
                  <span className="run-history-name">{run.workflow_name}</span>
                  <span className="run-history-meta">
                    <span className={`trace-status trace-status--${run.status}`}>{run.status}</span>
                    {' · '}{run.step_count} step{run.step_count === 1 ? '' : 's'}
                    {run.evaluation_score !== null && <> · score {run.evaluation_score}/10</>}
                    {' · '}{formatRunTime(run.created_at)}
                    {run.truncated && <span title="Step inputs and outputs were dropped to fit the size limit"> · trimmed</span>}
                  </span>
                </div>
                <div className="run-history-actions">
                  <button className="btn btn-primary" disabled={busyId === run.id} onClick={() => handleReplay(run.id)}>
                    Replay
                  </button>
                  <button
                    className="btn btn-ghost"
                    disabled={busyId === run.id}
                    onClick={() => handleDelete(run.id)}
                    aria-label={`Delete run of ${run.workflow_name}`}
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>

          {loading && <div className="run-history-empty">Loading…</div>}
          {hasMore && !loading && (
            <button className="btn btn-ghost" onClick={() => load(runs.length)}>Load more</button>
          )}
        </div>
      </div>
    </div>
  );
}
