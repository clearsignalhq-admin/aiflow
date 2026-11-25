import { useCallback, useEffect, useState } from 'react';
import type { Workflow } from '../../models/workflow';
import type { ExposureReport, ResilienceReport } from '../../models/safety';
import { useAuth } from '../../context/AuthContext';
import { safetyApi } from '../../services/safety';
import { HelpIcon } from '../../components/HelpIcon';

interface Props {
  workflow: Workflow;
  onSelectNode?: (nodeId: string) => void;
  onClose: () => void;
}

const messageOf = (err: unknown) => (err instanceof Error ? err.message : 'Something went wrong.');
const VERDICT_LABEL = { ignored: 'Not noticed', halted: 'Stops', handled: 'Handled' } as const;

function sampleInput(workflow: Workflow): Record<string, unknown> {
  const s = (workflow.metadata as Record<string, unknown> | undefined)?.sample_input;
  return s && typeof s === 'object' && !Array.isArray(s) ? (s as Record<string, unknown>) : {};
}

export function SafetyModal({ workflow, onSelectNode, onClose }: Props) {
  const { session } = useAuth();
  const token = session?.access_token;
  const [exposure, setExposure] = useState<ExposureReport | null>(null);
  const [drill, setDrill] = useState<ResilienceReport | null>(null);
  const [drilling, setDrilling] = useState(false);
  const [error, setError] = useState('');

  const loadExposure = useCallback(async () => {
    try {
      setExposure(await safetyApi.exposure(token, workflow));
    } catch (err) {
      setError(messageOf(err));
    }
  }, [token, workflow]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch once when the dialog opens
    void loadExposure();
  }, [loadExposure]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const runDrill = async () => {
    setDrilling(true);
    setError('');
    setDrill(null);
    try {
      setDrill(await safetyApi.resilience(token, workflow, sampleInput(workflow)));
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setDrilling(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal suggest-modal" role="dialog" aria-label="Safety checks">
        <div className="modal-header">
          <span className="modal-title">
            Safety checks
            <HelpIcon
              title="Safety checks"
              guide="safety-checks"
              body="Two checks that need no AI and no setup.\n\nInjection exposure looks at the design: where text from a user, a document, an API or a database could steer an AI step into an action that changes something.\n\nThe failure drill makes each outside step fail in turn (error, timeout, empty, malformed) in a simulated run, and reports whether the workflow notices, stops, or carries on as if nothing happened."
            />
          </span>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="modal-body suggest-body">
          {error && <div className="modal-error" role="alert">{error}</div>}

          <div className="suite-coverage-title">Prompt-injection exposure</div>
          {exposure === null && !error && <div className="run-history-empty">Analysing…</div>}
          {exposure && exposure.exposures.length === 0 && (
            <div className="suite-hint" data-testid="no-exposure">{exposure.notes[0] ?? 'No exposure found.'}</div>
          )}
          {exposure && exposure.exposures.length > 0 && (
            <ul className="change-list" data-testid="exposures">
              {exposure.exposures.map((x) => (
                <li key={x.node_id} className={`change-card safety-card--${x.severity}`} data-testid="exposure">
                  <div className="change-card-head">
                    <span className="change-card-title">
                      <span className={`cmp-badge safety-badge--${x.severity}`}>{x.severity}</span> {x.name}
                    </span>
                    {onSelectNode && <button className="btn btn-ghost" onClick={() => onSelectNode(x.node_id)}>Show</button>}
                  </div>
                  <div className="safety-message">{x.message}</div>
                  <div className="suite-hint">{x.advice}</div>
                </li>
              ))}
            </ul>
          )}

          <div className="suite-coverage-title">Failure drill</div>
          <div>
            <button className="btn btn-primary" disabled={drilling} onClick={() => void runDrill()}>
              {drilling ? <><span className="spinner" /> Running…</> : 'Run failure drill'}
            </button>
            <span className="suite-hint"> Simulated, no AI. Uses the sample input; counts as one run.</span>
          </div>
          {drill && (
            <div data-testid="drill">
              {drill.results.length > 0 && (
                <div className="suite-counts" data-testid="drill-counts">
                  <span className="suite-count--fail">{drill.summary.ignored} not noticed</span>
                  {' · '}{drill.summary.halted} stop the run
                  {' · '}<span className="suite-count--pass">{drill.summary.handled} handled</span>
                  {' '}(of {drill.summary.total})
                </div>
              )}
              {drill.notes.map((n) => <div key={n} className="suite-hint">{n}</div>)}
              <ul className="change-list">
                {drill.results.map((r) => (
                  <li key={`${r.node_id}-${r.kind}`} className="change-card" data-testid="drill-result">
                    <div className="change-card-head">
                      <span className="change-card-title">
                        <span className={`cmp-badge safety-verdict--${r.verdict}`}>{VERDICT_LABEL[r.verdict]}</span> {r.node_name}
                        <span className="suite-hint"> · {r.kind}</span>
                      </span>
                    </div>
                    <div className="suite-hint">{r.detail}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
