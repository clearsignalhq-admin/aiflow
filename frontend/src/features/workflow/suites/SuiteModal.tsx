import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Workflow } from '../../../models/workflow';
import type { LlmMode, RunEstimate, SuiteRunDetail, SuiteRunSummary, SuiteSummary } from '../../../models/suites';
import { useAuth } from '../../../context/AuthContext';
import { ApiError, suiteApi } from '../../../services/suites';
import { executeSuite } from '../../../services/suiteExecutor';
import { HelpIcon } from '../../../components/HelpIcon';
import { SuiteCasesEditor } from './SuiteCasesEditor';
import { SuiteReport } from './SuiteReport';
import { percent } from './format';
import { blankCase, caseProblem } from './assertionUtils';
import { fromDraft, serializeSuite, toDraft } from './draftUtils';
import type { DraftCase } from './draftUtils';

interface Props {
  workflow: Workflow;
  onClose: () => void;
}

const DEMO_MAX_CASES = 10;
const APPROVED_MAX_CASES = 50;

const message = (err: unknown) => (err instanceof Error ? err.message : 'Something went wrong.');

export function SuiteModal({ workflow, onClose }: Props) {
  const { session, profile } = useAuth();
  const token = session?.access_token;
  const maxCases = profile?.role === 'demo' ? DEMO_MAX_CASES : APPROVED_MAX_CASES;
  const nodes = useMemo(() => workflow.nodes.map((n) => ({ id: n.id, name: n.name })), [workflow.nodes]);
  const nodeNames = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n.name])), [nodes]);
  const sampleInput = workflow.metadata?.sample_input as Record<string, unknown> | undefined;

  const [suites, setSuites] = useState<SuiteSummary[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [draft, setDraft] = useState<DraftCase[]>([]);
  const [savedSnapshot, setSavedSnapshot] = useState('');
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [run, setRun] = useState<SuiteRunDetail | null>(null);
  const [pastRuns, setPastRuns] = useState<SuiteRunSummary[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const [llmMode, setLlmMode] = useState<LlmMode>('mock');
  const [estimate, setEstimate] = useState<RunEstimate | null>(null);
  const [estimating, setEstimating] = useState(false);

  const dirty = selectedId !== null && serializeSuite(name, draft) !== savedSnapshot;
  const firstProblem = draft.map((d) => caseProblem(d.data)).find((p) => p !== null) ?? null;

  const refreshPastRuns = useCallback(async (suiteId: string) => {
    try {
      setPastRuns(await suiteApi.listRuns(token, suiteId));
    } catch {
      setPastRuns([]);
    }
  }, [token]);

  const openSuite = useCallback(async (suiteId: string) => {
    setError('');
    setRun(null);
    try {
      const detail = await suiteApi.get(token, suiteId);
      const cases = detail.cases.map((c) => ({ ...c, tags: c.tags ?? [], assertions: c.assertions ?? [] }));
      const nextDraft = toDraft(cases);
      setSelectedId(detail.id);
      setName(detail.name);
      setDraft(nextDraft);
      setSavedSnapshot(serializeSuite(detail.name, nextDraft));
      void refreshPastRuns(detail.id);
    } catch (err) {
      setError(message(err));
    }
  }, [token, refreshPastRuns]);

  // Initial load: list this workflow's suites and open the first one.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await suiteApi.list(token, workflow.id);
        if (cancelled) return;
        setSuites(list);
        if (list.length > 0) await openSuite(list[0].id);
      } catch (err) {
        if (!cancelled) {
          setSuites([]);
          setError(message(err));
        }
      }
    })();
    return () => { cancelled = true; };
  }, [token, workflow.id, openSuite]);

  useEffect(() => () => abortRef.current?.abort(), []);

  // What a real-model run would use. Asked of the server (it knows the allowance); refreshed when the
  // saved suite or the workflow changes. Mock runs are free, so nothing is asked for them.
  useEffect(() => {
    if (llmMode !== 'real' || !selectedId || savedSnapshot === '') return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- loading state for the request below
    setEstimating(true);
    suiteApi.estimateRun(token, selectedId, workflow, 'real')
      .then((e) => { if (!cancelled) setEstimate(e); })
      .catch((err) => { if (!cancelled) setEstimate({ cases: 0, llm_mode: 'real', llm_calls_per_case_max: 0, llm_calls_max: 0, cost_usd_max: 0, executions_needed: 0, executions_remaining: null, llm_requests_remaining: null, allowed: false, reason: message(err), warnings: [] }); })
      .finally(() => { if (!cancelled) setEstimating(false); });
    return () => { cancelled = true; };
  }, [llmMode, selectedId, savedSnapshot, workflow, token]);

  const confirmDiscard = () => !dirty || window.confirm('You have unsaved changes to this suite. Discard them?');

  const handleClose = () => {
    if (running) return;
    if (confirmDiscard()) onClose();
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !running && (!dirty || window.confirm('You have unsaved changes to this suite. Discard them?'))) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, running, dirty]);

  const handleSelect = async (id: string) => {
    if (!id || id === selectedId || !confirmDiscard()) return;
    await openSuite(id);
  };

  const handleCreate = async () => {
    if (!confirmDiscard()) return;
    setBusy(true);
    setError('');
    try {
      const title = `Suite ${(suites?.length ?? 0) + 1}`;
      const created = await suiteApi.create(token, workflow.id, title, [blankCase(1, sampleInput)]);
      setSuites((prev) => [{ id: created.id, workflow_id: created.workflow_id, name: created.name, case_count: created.cases.length, updated_at: created.updated_at }, ...(prev ?? [])]);
      await openSuite(created.id);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  const save = async (): Promise<boolean> => {
    if (!selectedId) return false;
    if (firstProblem) { setError(firstProblem); return false; }
    setBusy(true);
    setError('');
    try {
      const saved = await suiteApi.update(token, selectedId, name.trim() || 'Untitled suite', fromDraft(draft));
      // Keep the editor's own keys (so open cards stay open); just adopt the server-assigned case ids.
      const nextDraft = draft.map((d, i) => ({ key: d.key, data: { ...d.data, id: saved.cases[i]?.id ?? d.data.id } }));
      setDraft(nextDraft);
      setName(saved.name);
      setSavedSnapshot(serializeSuite(saved.name, nextDraft));
      setSuites((prev) => (prev ?? []).map((s) => (s.id === saved.id ? { ...s, name: saved.name, case_count: saved.cases.length, updated_at: saved.updated_at } : s)));
      return true;
    } catch (err) {
      setError(message(err));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedId || !window.confirm(`Delete the suite "${name}" and its run history?`)) return;
    setBusy(true);
    try {
      await suiteApi.remove(token, selectedId);
      const remaining = (suites ?? []).filter((s) => s.id !== selectedId);
      setSuites(remaining);
      setSelectedId(null);
      setDraft([]);
      setName('');
      setSavedSnapshot('');
      setRun(null);
      setPastRuns([]);
      if (remaining.length > 0) await openSuite(remaining[0].id);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  const handleRun = async () => {
    if (!selectedId || running) return;
    if (dirty && !(await save())) return;
    if (draft.length === 0) { setError('Add at least one test case first.'); return; }
    if (llmMode === 'real') {
      if (!estimate || !estimate.allowed) { setError(estimate?.reason ?? 'The estimate is not ready yet.'); return; }
      const ok = window.confirm(
        `Run ${estimate.cases} case${estimate.cases === 1 ? '' : 's'} with the real AI model?\n\n` +
        `Up to ${estimate.llm_calls_max} model calls (about $${estimate.cost_usd_max.toFixed(3)}), counted against your daily AI request allowance. ` +
        'Results can differ between runs.',
      );
      if (!ok) return;
    }

    setError('');
    setRunning(true);
    const controller = new AbortController();
    abortRef.current = controller;
    let runId: string | null = null;
    try {
      const created = await suiteApi.createRun(token, selectedId, workflow, 0, llmMode);
      runId = created.id;
      setRun(created);

      const outcome = await executeSuite({
        caseIds: created.cases.map((c) => c.id),
        runCase: (caseId) => suiteApi.runCase(token, created.id, caseId),
        signal: controller.signal,
        onResult: (result) => setRun((prev) => (prev && !prev.results.some((r) => r.case_id === result.case_id)
          ? { ...prev, results: [...prev.results, result] }
          : prev)),
      });

      if (outcome.stoppedReason || outcome.cancelled) {
        // Close the job so it does not sit as "running"; the report then shows what did complete.
        await suiteApi.cancelRun(token, created.id).catch(() => undefined);
      }
      setRun(await suiteApi.getRun(token, created.id));
      if (outcome.stoppedReason) setError(`Stopped early: ${outcome.stoppedReason}`);
    } catch (err) {
      setError(message(err));
      if (runId) setRun(await suiteApi.getRun(token, runId).catch(() => null));
    } finally {
      setRunning(false);
      abortRef.current = null;
      void refreshPastRuns(selectedId);
    }
  };

  const handleViewRun = async (runId: string) => {
    try {
      setError('');
      setRun(await suiteApi.getRun(token, runId));
    } catch (err) {
      setError(message(err instanceof ApiError ? err : new Error('Could not load that run.')));
    }
  };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && handleClose()}>
      <div className="modal suite-modal" role="dialog" aria-label="Test suites">
        <div className="modal-header">
          <span className="modal-title">
            Test Suites
            <HelpIcon
              title="Test Suites"
              body="A suite is a set of test cases for this workflow. Each case has an input and checks (assertions) on the final output, for example 'output.tier equals premium' or 'visits node Human Review'.\n\nRunning a suite simulates every case in mock mode with a reproducible seed and reports a pass rate, which nodes and branches were never exercised, and where failures concentrate. Each case counts as one simulation toward your daily allowance.\n\nChecks are deterministic: there is no AI judge, so the same suite gives the same result every time."
            />
          </span>
          <button className="modal-close" onClick={handleClose} aria-label="Close" disabled={running}>✕</button>
        </div>

        <div className="modal-body suite-body">
          {suites === null && <div className="run-history-empty">Loading…</div>}

          {suites !== null && (
            <div className="suite-toolbar">
              {suites.length > 0 && (
                <select
                  className="prop-input prop-select suite-select"
                  aria-label="Suite"
                  value={selectedId ?? ''}
                  disabled={running || busy}
                  onChange={(e) => void handleSelect(e.target.value)}
                >
                  {suites.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.case_count})</option>)}
                </select>
              )}
              <button className="btn btn-ghost" onClick={handleCreate} disabled={running || busy}>+ New suite</button>
              {selectedId && (
                <button className="btn btn-ghost" onClick={handleDelete} disabled={running || busy}>Delete suite</button>
              )}
            </div>
          )}

          {suites !== null && suites.length === 0 && !error && (
            <div className="run-history-empty">
              No test suites for this workflow yet. Create one to check how it behaves for different inputs.
            </div>
          )}

          {error && <div className="modal-error" role="alert">{error}</div>}

          {selectedId && (
            <>
              <div className="suite-name-row">
                <label className="prop-label" htmlFor="suite-name">Suite name</label>
                <input id="suite-name" className="prop-input" value={name} disabled={running} onChange={(e) => setName(e.target.value)} />
              </div>

              <SuiteCasesEditor
                cases={draft}
                nodes={nodes}
                maxCases={maxCases}
                sampleInput={sampleInput}
                disabled={running}
                onChange={setDraft}
              />

              <div className="suite-actions">
                <button className="btn btn-ghost" onClick={() => void save()} disabled={!dirty || busy || running}>
                  {dirty ? 'Save changes' : 'Saved'}
                </button>
                <button
                  className="btn btn-primary"
                  onClick={() => void handleRun()}
                  disabled={running || busy || draft.length === 0 || (llmMode === 'real' && (estimating || !estimate?.allowed))}
                >
                  {running ? <><span className="spinner" /> Running…</>
                    : `▶ Run ${draft.length} case${draft.length === 1 ? '' : 's'}${llmMode === 'real' ? ' with the real model' : ''}`}
                </button>
                {running && (
                  <button className="btn btn-ghost" onClick={() => abortRef.current?.abort()}>Stop</button>
                )}
                <span className="suite-hint">
                  {llmMode === 'real' ? 'Each case uses one daily simulation plus its model calls' : 'Mock mode · each case uses one of your daily simulations'}
                </span>
              </div>

              <fieldset className="suite-mode" disabled={running}>
                <legend className="prop-label">AI model</legend>
                <label>
                  <input type="radio" name="suite-llm-mode" checked={llmMode === 'mock'} onChange={() => setLlmMode('mock')} />
                  {' '}Simulated (free, same result every time)
                </label>
                <label>
                  <input type="radio" name="suite-llm-mode" checked={llmMode === 'real'} onChange={() => setLlmMode('real')} />
                  {' '}Real model (uses your AI request allowance; answers can vary)
                </label>
              </fieldset>

              {llmMode === 'real' && (
                <div className={`suite-estimate${estimate && !estimate.allowed ? ' suite-estimate--blocked' : ''}`} data-testid="estimate">
                  {estimating && <span>Estimating…</span>}
                  {!estimating && estimate && (
                    <>
                      {estimate.allowed ? (
                        <div>
                          Up to <strong>{estimate.llm_calls_max}</strong> model calls
                          ({estimate.llm_calls_per_case_max} per case, about ${estimate.cost_usd_max.toFixed(3)})
                          {estimate.llm_requests_remaining !== null && <> · {estimate.llm_requests_remaining} AI requests left today</>}
                        </div>
                      ) : (
                        <div role="alert">{estimate.reason}</div>
                      )}
                      {estimate.warnings.map((w) => <div key={w} className="suite-hint">{w}</div>)}
                    </>
                  )}
                </div>
              )}
            </>
          )}

          {run && <SuiteReport run={run} nodeNames={nodeNames} />}

          {pastRuns.length > 0 && (
            <div className="suite-history">
              <div className="suite-coverage-title">Previous runs</div>
              <ul className="suite-history-list">
                {pastRuns.map((r) => {
                  const done = r.passed + r.failed + r.errors;
                  return (
                    <li key={r.id}>
                      <button className="btn btn-ghost" onClick={() => void handleViewRun(r.id)} disabled={running}>
                        {new Date(r.created_at).toLocaleString()} — {percent(done ? r.passed / done : null)} passed ({r.passed}/{r.case_count}) · {r.status}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
