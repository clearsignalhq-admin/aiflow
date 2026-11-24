import { useEffect, useMemo, useState } from 'react';
import type { Workflow } from '../../models/workflow';
import { mermaidToWorkflow, workflowToMermaid } from '../../services/mermaid';
import { copyText, downloadText } from '../../utils/download';
import { HelpIcon } from '../../components/HelpIcon';

interface Props {
  workflow: Workflow;
  /** Called with the imported workflow; the caller decides about unsaved work. */
  onImport: (workflow: Workflow) => void;
  onClose: () => void;
}

type Tab = 'export' | 'import';

function fileName(name: string): string {
  return `${name.trim().replace(/\s+/g, '-').replace(/[^a-zA-Z0-9-_]/g, '').toLowerCase() || 'workflow'}.mmd`;
}

export function MermaidModal({ workflow, onImport, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('export');
  const [source, setSource] = useState('');
  const [copied, setCopied] = useState<'yes' | 'no' | null>(null);

  const exported = useMemo(() => workflowToMermaid(workflow), [workflow]);
  const imported = useMemo(() => (source.trim() ? mermaidToWorkflow(source) : null), [source]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const handleCopy = async () => {
    setCopied((await copyText(exported)) ? 'yes' : 'no');
  };

  const handleLoad = () => {
    if (!imported?.workflow) return;
    onImport(imported.workflow);
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal mermaid-modal" role="dialog" aria-label="Mermaid">
        <div className="modal-header">
          <span className="modal-title">
            Mermaid
            <HelpIcon
              title="Mermaid diagrams"
              body="Mermaid is a text format for diagrams that GitHub, GitLab, Notion and many docs tools render directly, so a workflow can live in a README or pull request.\n\nExport writes the workflow's shape: node types, names, and branch labels. Node settings (prompts, URLs, expressions, schemas) are not part of a diagram.\n\nImport reads flowcharts written by AiFlow or by hand. Node types are taken from the shape or label; anything guessed is listed so you can fix it."
            />
          </span>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="sim-tabs mermaid-tabs">
          <button className={`sim-tab${tab === 'export' ? ' sim-tab--active' : ''}`} onClick={() => setTab('export')}>Export</button>
          <button className={`sim-tab${tab === 'import' ? ' sim-tab--active' : ''}`} onClick={() => setTab('import')}>Import</button>
        </div>

        <div className="modal-body">
          {tab === 'export' && (
            <>
              <p className="modal-hint">
                Paste this into a README, a pull request or <strong>mermaid.live</strong> to see the diagram. Node settings are not included.
              </p>
              <textarea className="modal-textarea mermaid-text" readOnly value={exported} aria-label="Mermaid diagram" spellCheck={false} />
              <div className="suite-actions">
                <button className="btn btn-primary" onClick={() => void handleCopy()}>Copy</button>
                <button className="btn btn-ghost" onClick={() => downloadText(exported, fileName(workflow.name), 'text/vnd.mermaid')}>Download .mmd</button>
                {copied === 'yes' && <span className="suite-hint" role="status">Copied</span>}
                {copied === 'no' && <span className="assertion-problem" role="status">Copy was blocked by the browser; select the text and copy it manually.</span>}
              </div>
            </>
          )}

          {tab === 'import' && (
            <>
              <p className="modal-hint">
                Paste a Mermaid <code>flowchart</code>. Importing replaces the current workflow (you are asked first if it has unsaved changes).
              </p>
              <textarea
                className="modal-textarea mermaid-text"
                value={source}
                onChange={(e) => setSource(e.target.value)}
                placeholder={'flowchart TD\n  start(["Start"]) --> check{"Is it urgent?"}\n  check -->|yes| act["Handle now"]\n  check -->|no| done(["End"])\n  act --> done'}
                aria-label="Mermaid source"
                spellCheck={false}
              />

              {imported && imported.errors.length > 0 && (
                <ul className="validation-list validation-list--errors" role="alert">
                  {imported.errors.map((m, i) => <li key={i}>{m}</li>)}
                </ul>
              )}
              {imported?.workflow && (
                <>
                  <div className="suite-hint" data-testid="import-summary">
                    Ready to import “{imported.workflow.name}”: {imported.workflow.nodes.length} nodes, {imported.workflow.edges.length} edges.
                  </div>
                  {imported.warnings.length > 0 && (
                    <ul className="validation-list validation-list--warnings">
                      {imported.warnings.map((m, i) => <li key={i}>{m}</li>)}
                    </ul>
                  )}
                </>
              )}
              <div className="suite-actions">
                <button className="btn btn-primary" onClick={handleLoad} disabled={!imported?.workflow}>Import as workflow</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
