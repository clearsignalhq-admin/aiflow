import { useEffect, useState } from 'react';
import type { Workflow } from '../../models/workflow';
import type { SuiteSummary } from '../../models/suites';
import { useAuth } from '../../context/AuthContext';
import { suiteApi } from '../../services/suites';
import { EXPORT_NOTES, exportLangGraph } from '../../services/codeExport';
import { downloadBlob } from '../../utils/download';
import { HelpIcon } from '../../components/HelpIcon';

interface Props {
  workflow: Workflow;
  onClose: () => void;
}

export function ExportCodeModal({ workflow, onClose }: Props) {
  const { session } = useAuth();
  const token = session?.access_token;
  const [suites, setSuites] = useState<SuiteSummary[]>([]);
  const [suiteId, setSuiteId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    suiteApi.list(token, workflow.id)
      .then((list) => { if (!cancelled) setSuites(list.filter((s) => s.case_count > 0)); })
      .catch(() => undefined);                       // tests are optional; the export works without them
    return () => { cancelled = true; };
  }, [token, workflow.id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, busy]);

  const handleDownload = async () => {
    setBusy(true);
    setError('');
    setDone(null);
    try {
      const project = await exportLangGraph(token, workflow, suiteId || undefined);
      downloadBlob(project.blob, project.filename);
      setDone(project.filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The export failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="modal export-modal" role="dialog" aria-label="Export code">
        <div className="modal-header">
          <span className="modal-title">
            Export as code
            <HelpIcon
              title="Export as code"
              body="Downloads the workflow as a runnable LangGraph project in Python: a graph, one function per step, routing for decisions, human-review pauses, a command-line runner and tests.\n\nThe workflow itself is included as workflow.json and every step reads its settings from there. Steps that talk to other systems (tools, APIs, databases, knowledge search) are stubs that return fixtures, so the project runs end to end today and you replace them one by one.\n\nPick a test suite to also get one generated test per case, replayed with the same seeds and checks."
            />
          </span>
          <button className="modal-close" onClick={onClose} aria-label="Close" disabled={busy}>✕</button>
        </div>

        <div className="modal-body">
          <p className="modal-hint">
            A Python project using <strong>LangGraph</strong> for “{workflow.name}”. Run it offline with <code>--mock</code>, or with your own API key.
          </p>

          <label className="prop-label" htmlFor="export-suite">Generate tests from a test suite</label>
          <select
            id="export-suite"
            className="prop-input prop-select"
            value={suiteId}
            disabled={busy}
            onChange={(e) => setSuiteId(e.target.value)}
          >
            <option value="">None (just a smoke test)</option>
            {suites.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.case_count} cases)</option>)}
          </select>

          <div className="suite-coverage-title">Good to know</div>
          <ul className="export-notes">
            {EXPORT_NOTES.map((n) => <li key={n}>{n}</li>)}
          </ul>

          {error && <div className="modal-error" role="alert">{error}</div>}
          {done && (
            <div className="export-done" role="status">
              <strong>{done}</strong> downloaded. Unzip it, then:
              <pre className="trace-step-json">{'pip install -r requirements.txt\npython main.py --mock\npytest'}</pre>
            </div>
          )}

          <div className="suite-actions">
            <button className="btn btn-primary" onClick={() => void handleDownload()} disabled={busy}>
              {busy ? <><span className="spinner" /> Preparing…</> : 'Download project (.zip)'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
