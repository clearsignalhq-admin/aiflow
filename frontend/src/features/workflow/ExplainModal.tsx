import { useCallback, useEffect, useState } from 'react';
import type { Workflow } from '../../models/workflow';
import { API_BASE } from '../../config';
import { useAuth } from '../../context/AuthContext';
import { formatApiError } from '../../utils/apiError';
import { copyText, downloadText } from '../../utils/download';
import { MarkdownView } from '../../components/MarkdownView';
import { HelpIcon } from '../../components/HelpIcon';

interface Props {
  workflow: Workflow;
  onClose: () => void;
}

function fileName(name: string): string {
  return `${name.trim().replace(/\s+/g, '-').replace(/[^a-zA-Z0-9-_]/g, '').toLowerCase() || 'workflow'}-explained.md`;
}

export function ExplainModal({ workflow, onClose }: Props) {
  const { session } = useAuth();
  const token = session?.access_token;
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState<'yes' | 'no' | null>(null);

  const load = useCallback(async () => {
    setError('');
    setMarkdown(null);
    try {
      const res = await fetch(`${API_BASE}/api/workflows/explain`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ workflow }),
      });
      const data = await res.json().catch(() => null) as { markdown?: string } | null;
      if (!res.ok || typeof data?.markdown !== 'string') {
        setError(formatApiError(data, res.status));
        return;
      }
      setMarkdown(data.markdown);
    } catch {
      setError('Could not reach backend. Is it running on port 8000?');
    }
  }, [token, workflow]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch once when the dialog opens
    void load();
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal explain-modal" role="dialog" aria-label="Explain workflow">
        <div className="modal-header">
          <span className="modal-title">
            Explain this workflow
            <HelpIcon
              title="Explain this workflow"
              guide="checking-your-design"
              body="A plain-language description built directly from the workflow: what happens step by step, where people review things, what it connects to, rough time and cost, and anything the automatic checks flagged.\n\nIt is generated from the design without using the AI model, so it is free, always matches the current workflow, and gives the same text for the same workflow. Copy or download it as Markdown to share with reviewers."
            />
          </span>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="modal-body explain-body">
          {markdown === null && !error && <div className="run-history-empty">Writing the explanation…</div>}
          {error && <div className="modal-error" role="alert">{error}</div>}
          {markdown !== null && <MarkdownView source={markdown} />}
        </div>

        <div className="suite-actions explain-actions">
          <button className="btn btn-primary" disabled={markdown === null} onClick={async () => setCopied((await copyText(markdown ?? '')) ? 'yes' : 'no')}>
            Copy Markdown
          </button>
          <button className="btn btn-ghost" disabled={markdown === null} onClick={() => downloadText(markdown ?? '', fileName(workflow.name), 'text/markdown')}>
            Download .md
          </button>
          <button className="btn btn-ghost" onClick={() => void load()}>Refresh</button>
          {copied === 'yes' && <span className="suite-hint" role="status">Copied</span>}
          {copied === 'no' && <span className="assertion-problem" role="status">Copy was blocked by the browser.</span>}
        </div>
      </div>
    </div>
  );
}
