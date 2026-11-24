import { useCallback, useEffect, useState } from 'react';
import type { Workflow } from '../../models/workflow';
import type { SuggestedChange, SuggestResult } from '../../models/changes';
import { useAuth } from '../../context/AuthContext';
import { changeApi } from '../../services/changes';
import { HelpIcon } from '../../components/HelpIcon';

interface Props {
  workflow: Workflow;
  /** Receives the edited workflow; the caller records it as one undoable edit. */
  onApply: (workflow: Workflow, appliedCount: number) => void;
  onClose: () => void;
}

const messageOf = (err: unknown) => (err instanceof Error ? err.message : 'Something went wrong.');

function ChangeCard({ change, busy, onApply }: { change: SuggestedChange; busy: boolean; onApply: () => void }) {
  return (
    <li className="change-card" data-testid="change-card">
      <div className="change-card-head">
        <span className="change-card-title">{change.title}</span>
        <button className="btn btn-primary" disabled={busy} onClick={onApply} aria-label={`Apply: ${change.title}`}>Apply</button>
      </div>
      {change.rationale && <div className="suite-hint">{change.rationale}</div>}
      <ul className="change-card-ops">
        {change.summary.map((line, i) => <li key={i}>{line}</li>)}
      </ul>
    </li>
  );
}

export function SuggestionsModal({ workflow, onApply, onClose }: Props) {
  const { session } = useAuth();
  const token = session?.access_token;
  const [fixes, setFixes] = useState<SuggestedChange[] | null>(null);
  const [ai, setAi] = useState<SuggestResult | null>(null);
  const [instruction, setInstruction] = useState('');
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');

  const loadFixes = useCallback(async () => {
    try {
      setFixes(await changeApi.fixes(token, workflow));
    } catch (err) {
      setFixes([]);
      setError(messageOf(err));
    }
  }, [token, workflow]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reload whenever the workflow changes (e.g. after applying)
    void loadFixes();
  }, [loadFixes]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const apply = async (changes: SuggestedChange[]) => {
    setBusy(true);
    setError('');
    setNote('');
    try {
      const result = await changeApi.apply(token, workflow, changes);
      if (result.applied.length > 0) {
        onApply(result.workflow, result.applied.length);
        setAi((prev) => (prev ? { ...prev, changes: prev.changes.filter((c) => !result.applied.includes(c.id)) } : prev));
      }
      const skipped = result.skipped.map((s) => `“${changes.find((c) => c.id === s.id)?.title ?? s.id}”: ${s.reason}`);
      setNote(
        `${result.applied.length} change${result.applied.length === 1 ? '' : 's'} applied. Undo (Ctrl+Z) reverts them.` +
        (skipped.length ? ` Not applied — ${skipped.join(' ')}` : ''),
      );
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  const ask = async () => {
    setAsking(true);
    setError('');
    setNote('');
    setAi(null);
    try {
      setAi(await changeApi.suggest(token, workflow, instruction.trim()));
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal suggest-modal" role="dialog" aria-label="Suggested changes">
        <div className="modal-header">
          <span className="modal-title">
            Suggested changes
            <HelpIcon
              title="Suggested changes"
              body="Fixes for what the design checks flag are worked out directly from the workflow, so they are free and always the same. You can also describe a change in your own words and the AI will propose edits (this uses one AI request).\n\nNothing changes until you press Apply. Each suggestion is applied all together or not at all, is checked by the server first, and can be undone with Ctrl+Z."
            />
          </span>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="modal-body suggest-body">
          {error && <div className="modal-error" role="alert">{error}</div>}
          {note && <div className="suite-hint" role="status">{note}</div>}

          <div className="suite-coverage-title">Fixes for design findings</div>
          {fixes === null && <div className="run-history-empty">Looking for fixes…</div>}
          {fixes !== null && fixes.length === 0 && (
            <div className="suite-hint" data-testid="no-fixes">No automatic fixes to suggest right now.</div>
          )}
          {fixes !== null && fixes.length > 0 && (
            <>
              <ul className="change-list">
                {fixes.map((c) => <ChangeCard key={c.id} change={c} busy={busy} onApply={() => void apply([c])} />)}
              </ul>
              {fixes.length > 1 && (
                <button className="btn btn-ghost" disabled={busy} onClick={() => void apply(fixes)}>Apply all {fixes.length} fixes</button>
              )}
            </>
          )}

          <div className="suite-coverage-title">Describe a change</div>
          <textarea
            className="prop-input"
            aria-label="Describe the change"
            rows={3}
            maxLength={1000}
            placeholder="For example: add a human approval before the refund is issued"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
          />
          <div>
            <button className="btn btn-primary" disabled={asking || instruction.trim().length < 3} onClick={() => void ask()}>
              {asking ? <><span className="spinner" /> Thinking…</> : 'Suggest changes'}
            </button>
            <span className="suite-hint"> Uses one AI request.</span>
          </div>

          {ai && (
            <div data-testid="ai-result">
              {ai.summary && <div className="suite-hint">{ai.summary}</div>}
              {ai.changes.length === 0 && <div className="suite-hint">The AI had no usable changes to suggest.</div>}
              <ul className="change-list">
                {ai.changes.map((c) => <ChangeCard key={c.id} change={c} busy={busy} onApply={() => void apply([c])} />)}
              </ul>
              {ai.discarded.length > 0 && (
                <ul className="validation-list validation-list--warnings" data-testid="ai-discarded">
                  {ai.discarded.map((d, i) => <li key={i}>{d}</li>)}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
