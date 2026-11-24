import { useEffect, useState } from 'react';
import type { Workflow } from '../../models/workflow';
import type { SuiteSummary } from '../../models/suites';
import { useAuth } from '../../context/AuthContext';
import { suiteApi } from '../../services/suites';
import { EXPORT_TARGETS, exportProject, importLangGraph, readFiles } from '../../services/codeExport';
import type { ImportedCode } from '../../services/codeExport';
import { autoLayoutWorkflow } from './WorkflowAdapter';
import type { ExportTarget } from '../../services/codeExport';
import { downloadBlob } from '../../utils/download';
import { HelpIcon } from '../../components/HelpIcon';

interface Props {
  workflow: Workflow;
  /** Called with a workflow read from code; the caller decides about unsaved work. */
  onImport?: (workflow: Workflow) => void;
  onClose: () => void;
}

type Tab = 'export' | 'import';

export function ExportCodeModal({ workflow, onImport, onClose }: Props) {
  const { session } = useAuth();
  const token = session?.access_token;
  const [suites, setSuites] = useState<SuiteSummary[]>([]);
  const [suiteId, setSuiteId] = useState('');
  const [target, setTarget] = useState<ExportTarget>('langgraph');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('export');
  const [uploaded, setUploaded] = useState<Record<string, string>>({});
  const [pasted, setPasted] = useState('');
  const [imported, setImported] = useState<ImportedCode | null>(null);
  const [importing, setImporting] = useState(false);

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

  const info = EXPORT_TARGETS.find((t) => t.id === target) ?? EXPORT_TARGETS[0];

  const sources = (): Record<string, string> => ({ ...uploaded, ...(pasted.trim() ? { 'pasted.py': pasted } : {}) });

  const handlePick = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(event.target.files ?? []);
    event.target.value = '';
    setError('');
    setImported(null);
    try {
      setUploaded({ ...uploaded, ...(await readFiles(picked)) });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not read the files.');
    }
  };

  const handleRead = async () => {
    setImporting(true);
    setError('');
    setImported(null);
    try {
      setImported(await importLangGraph(token, sources()));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The code could not be read.');
    } finally {
      setImporting(false);
    }
  };

  const handleImport = () => {
    if (!imported || !onImport) return;
    onImport(autoLayoutWorkflow(imported.workflow));
    onClose();
  };

  const handleDownload = async () => {
    setBusy(true);
    setError('');
    setDone(null);
    try {
      const project = await exportProject(token, workflow, target, info.supportsTests && suiteId ? suiteId : undefined);
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
            Code
            <HelpIcon
              title="Export as code"
              body="Downloads the workflow as a runnable project: LangGraph or plain Python (a graph or small engine, one function per step, routing for decisions, human-review pauses, a command-line runner and tests), or an MCP server that exposes the tool, API, database and knowledge-search steps to MCP clients.\n\nThe workflow itself is included as workflow.json and every step reads its settings from there. Steps that talk to other systems (tools, APIs, databases, knowledge search) are stubs that return fixtures, so the project runs end to end today and you replace them one by one.\n\nPick a test suite to also get one generated test per case, replayed with the same seeds and checks."
            />
          </span>
          <button className="modal-close" onClick={onClose} aria-label="Close" disabled={busy}>✕</button>
        </div>

        <div className="sim-tabs mermaid-tabs">
          <button className={`sim-tab${tab === 'export' ? ' sim-tab--active' : ''}`} onClick={() => { setTab('export'); setError(''); }}>Export</button>
          {onImport && (
            <button className={`sim-tab${tab === 'import' ? ' sim-tab--active' : ''}`} onClick={() => { setTab('import'); setError(''); }}>Import</button>
          )}
        </div>

        {tab === 'import' && onImport && (
          <div className="modal-body">
            <p className="modal-hint">
              Upload the Python files that build a <strong>LangGraph</strong> graph (usually <code>graph.py</code> and the files it imports), or paste the code.
              The code is only <em>read</em>, never run. An AiFlow export that includes <code>workflow.json</code> is restored exactly.
            </p>
            <input type="file" accept=".py,.json" multiple aria-label="Choose files" onChange={(e) => void handlePick(e)} />
            {Object.keys(uploaded).length > 0 && (
              <ul className="export-notes" aria-label="Chosen files">
                {Object.keys(uploaded).map((name) => (
                  <li key={name}>
                    {name}{' '}
                    <button
                      className="btn btn-ghost"
                      aria-label={`Remove ${name}`}
                      onClick={() => { const next = { ...uploaded }; delete next[name]; setUploaded(next); setImported(null); }}
                    >✕</button>
                  </li>
                ))}
              </ul>
            )}
            <label className="prop-label" htmlFor="import-paste">Or paste code</label>
            <textarea
              id="import-paste"
              className="modal-textarea mermaid-text"
              value={pasted}
              onChange={(e) => { setPasted(e.target.value); setImported(null); }}
              placeholder={'builder = StateGraph(State)\nbuilder.add_node("classify", classify)\nbuilder.add_edge(START, "classify")'}
              spellCheck={false}
            />
            {error && <div className="modal-error" role="alert">{error}</div>}
            {imported && (
              <>
                <div className="suite-hint" data-testid="import-summary">
                  {imported.mode === 'exact' ? 'Restored from workflow.json' : 'Read from the code'}: {imported.workflow.nodes.length} steps, {imported.workflow.edges.length} edges.
                </div>
                {imported.warnings.length > 0 && (
                  <ul className="validation-list validation-list--warnings">
                    {imported.warnings.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                )}
              </>
            )}
            <div className="suite-actions">
              <button className="btn btn-ghost" onClick={() => void handleRead()} disabled={importing || Object.keys(sources()).length === 0}>
                {importing ? <><span className="spinner" /> Reading…</> : 'Read code'}
              </button>
              <button className="btn btn-primary" onClick={handleImport} disabled={!imported}>Import as workflow</button>
            </div>
          </div>
        )}

        {tab === 'export' && (
        <div className="modal-body">
          <fieldset className="suite-mode export-targets" disabled={busy}>
            <legend className="prop-label">Format for “{workflow.name}”</legend>
            {EXPORT_TARGETS.map((t) => (
              <label key={t.id} className="export-target">
                <input type="radio" name="export-target" checked={target === t.id} onChange={() => setTarget(t.id)} />
                {' '}<strong>{t.label}</strong>
                <span className="suite-hint"> — {t.description}</span>
              </label>
            ))}
          </fieldset>

          {info.supportsTests && (
            <>
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
            </>
          )}

          <div className="suite-coverage-title">Good to know</div>
          <ul className="export-notes">
            {info.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>

          {error && <div className="modal-error" role="alert">{error}</div>}
          {done && (
            <div className="export-done" role="status">
              <strong>{done}</strong> downloaded. Unzip it, then:
              <pre className="trace-step-json">{info.nextSteps}</pre>
            </div>
          )}

          <div className="suite-actions">
            <button className="btn btn-primary" onClick={() => void handleDownload()} disabled={busy}>
              {busy ? <><span className="spinner" /> Preparing…</> : 'Download project (.zip)'}
            </button>
          </div>
        </div>
        )}
      </div>
    </div>
  );
}
