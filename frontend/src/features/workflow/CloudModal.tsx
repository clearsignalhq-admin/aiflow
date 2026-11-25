import { useCallback, useEffect, useState } from 'react';
import type { Workflow } from '../../models/workflow';
import type { CloudWorkflowSummary, VersionDiff, VersionSummary } from '../../models/cloud';
import { useAuth } from '../../context/AuthContext';
import { cloudApi, shareUrl } from '../../services/cloud';
import { copyText } from '../../utils/download';
import { HelpIcon } from '../../components/HelpIcon';
import { WorkflowDiffView } from './WorkflowDiffView';

interface Props {
  workflow: Workflow;
  /** The cloud workflow the editor is currently tied to, if any. */
  cloudId: string | null;
  /** Load a cloud copy into the editor. */
  onOpen: (workflow: Workflow, cloudId: string) => void;
  /** The editor is now tied to this cloud workflow (or to none, after a delete). */
  onCloudIdChange: (cloudId: string | null) => void;
  onClose: () => void;
}

const messageOf = (err: unknown) => (err instanceof Error ? err.message : 'Something went wrong.');
const when = (iso: string) => new Date(iso).toLocaleString();

export function CloudModal({ workflow, cloudId, onOpen, onCloudIdChange, onClose }: Props) {
  const { session } = useAuth();
  const token = session?.access_token;
  const [items, setItems] = useState<CloudWorkflowSummary[] | null>(null);
  const [name, setName] = useState(workflow.name);
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [versionsFor, setVersionsFor] = useState<string | null>(null);
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [diff, setDiff] = useState<{ version: number; result: VersionDiff } | null>(null);
  const [links, setLinks] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setItems(await cloudApi.list(token));
    } catch (err) {
      setItems([]);
      setError(messageOf(err));
    }
  }, [token]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load the list when the dialog opens
    void reload();
  }, [reload]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  /** Run one action with the busy flag and error handling shared by every button. */
  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError('');
    setNote('');
    try {
      await fn();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  const saveNew = () => act(async () => {
    const created = await cloudApi.create(token, name.trim() || workflow.name, workflow, label.trim());
    onCloudIdChange(created.id);
    setLabel('');
    setNote(`Saved “${created.name}” to the cloud.`);
    await reload();
  });

  const saveVersion = (id: string) => act(async () => {
    const saved = await cloudApi.save(token, id, workflow, label.trim());
    onCloudIdChange(id);   // the editor now matches the cloud copy
    setLabel('');
    setNote(saved.new_version ? `Saved as version ${saved.version_count}.` : 'Nothing has changed since the last save.');
    if (versionsFor === id) setVersions(await cloudApi.versions(token, id));
    await reload();
  });

  const open = (id: string) => act(async () => {
    const detail = await cloudApi.get(token, id);
    onOpen(detail.workflow, id);
    onClose();
  });

  const toggleVersions = (id: string) => act(async () => {
    if (versionsFor === id) {
      setVersionsFor(null);
      return;
    }
    setDiff(null);
    setVersions(await cloudApi.versions(token, id));
    setVersionsFor(id);
  });

  const showDiff = (id: string, version: number) => act(async () => {
    setDiff({ version, result: await cloudApi.diff(token, id, version) });
  });

  const restore = (id: string, version: number) => act(async () => {
    const restored = await cloudApi.restore(token, id, version);
    setDiff(null);
    setVersions(await cloudApi.versions(token, id));
    if (id === cloudId) onOpen(restored.workflow, id);   // keep the editor in step with the cloud copy
    setNote(restored.new_version ? `Version ${version} restored as version ${restored.version_count}.` : `Version ${version} is already the current copy.`);
    await reload();
  });

  const share = (id: string) => act(async () => {
    const { share_token } = await cloudApi.share(token, id);
    if (share_token) setLinks((l) => ({ ...l, [id]: shareUrl(share_token) }));
    await reload();
  });

  const unshare = (id: string) => act(async () => {
    await cloudApi.unshare(token, id);
    setLinks((l) => { const { [id]: _removed, ...rest } = l; void _removed; return rest; });
    setNote('The link has been turned off. Sharing again creates a new one.');
    await reload();
  });

  const remove = (item: CloudWorkflowSummary) => {
    if (!window.confirm(`Delete “${item.name}” and all ${item.version_count} of its versions? Its share link will stop working.`)) return Promise.resolve();
    return act(async () => {
      await cloudApi.remove(token, item.id);
      if (item.id === cloudId) onCloudIdChange(null);
      if (versionsFor === item.id) setVersionsFor(null);
      await reload();
    });
  };

  const copy = async (id: string, text: string) => {
    setCopied((await copyText(text)) ? id : null);
  };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal suggest-modal" role="dialog" aria-label="Cloud workflows">
        <div className="modal-header">
          <span className="modal-title">
            Cloud workflows
            <HelpIcon
              title="Cloud workflows"
              guide="saving-versions-and-sharing"
              body="Keep workflows in your account instead of a file. Every save that changes something adds a version, so you can see what changed since an earlier one and restore it (restoring adds a new version; nothing is lost). The newest 30 versions are kept.\n\nShare turns on a read-only link that anyone can open without signing in. It always shows the current copy and never lets them change it. Turn it off and the link stops working for good."
            />
          </span>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="modal-body suggest-body">
          {error && <div className="modal-error" role="alert">{error}</div>}
          {note && <div className="suite-hint" role="status">{note}</div>}

          <div className="suite-coverage-title">Save the workflow on screen</div>
          <input className="prop-input" aria-label="Name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
          <input className="prop-input" aria-label="Version note" value={label} maxLength={100} placeholder="Optional note for this version (for example: before adding approval)" onChange={(e) => setLabel(e.target.value)} />
          <div>
            <button className="btn btn-primary" disabled={busy} onClick={() => void saveNew()}>Save as new cloud workflow</button>
          </div>

          <div className="suite-coverage-title">Your cloud workflows</div>
          {items === null && <div className="run-history-empty">Loading…</div>}
          {items !== null && items.length === 0 && <div className="suite-hint" data-testid="cloud-empty">Nothing saved to the cloud yet.</div>}
          <ul className="change-list">
            {items?.map((item) => (
              <li key={item.id} className="change-card" data-testid="cloud-item">
                <div className="change-card-head">
                  <span className="change-card-title">
                    {item.name}
                    {item.id === cloudId && <span className="cmp-badge cmp-badge--unchanged"> open in editor</span>}
                  </span>
                  <span className="suite-hint">v{item.version_count} · {when(item.updated_at)}{item.shared ? ' · shared' : ''}</span>
                </div>
                <div className="suite-actions">
                  <button className="btn btn-ghost" disabled={busy} onClick={() => void open(item.id)} aria-label={`Open ${item.name}`}>Open</button>
                  {item.id === cloudId && (
                    <button className="btn btn-primary" disabled={busy} onClick={() => void saveVersion(item.id)} aria-label={`Save to ${item.name}`}>Save changes</button>
                  )}
                  <button className="btn btn-ghost" disabled={busy} onClick={() => void toggleVersions(item.id)} aria-label={`Versions of ${item.name}`}>Versions</button>
                  {item.shared
                    ? <button className="btn btn-ghost" disabled={busy} onClick={() => void unshare(item.id)} aria-label={`Stop sharing ${item.name}`}>Stop sharing</button>
                    : <button className="btn btn-ghost" disabled={busy} onClick={() => void share(item.id)} aria-label={`Share ${item.name}`}>Share</button>}
                  <button className="btn btn-ghost" disabled={busy} onClick={() => void remove(item)} aria-label={`Delete ${item.name}`}>Delete</button>
                </div>

                {item.shared && (
                  <div className="cloud-link">
                    {links[item.id]
                      ? <>
                          <input className="prop-input" readOnly aria-label="Share link" value={links[item.id]} onFocus={(e) => e.currentTarget.select()} />
                          <button className="btn btn-ghost" onClick={() => void copy(item.id, links[item.id])}>Copy link</button>
                          {copied === item.id && <span className="suite-hint" role="status">Copied</span>}
                        </>
                      : <button className="btn btn-ghost" disabled={busy} onClick={() => void share(item.id)}>Show link</button>}
                  </div>
                )}

                {versionsFor === item.id && (
                  <div data-testid="versions">
                    <ul className="change-card-ops">
                      {versions.map((v) => (
                        <li key={v.version}>
                          <strong>v{v.version}</strong> {v.label ? `“${v.label}” ` : ''}· {when(v.created_at)} · {v.node_count} steps
                          {' '}<button className="btn btn-ghost" disabled={busy} onClick={() => void showDiff(item.id, v.version)} aria-label={`Changes since version ${v.version}`}>Changes since</button>
                          {v.version !== item.version_count && (
                            <button className="btn btn-ghost" disabled={busy} onClick={() => void restore(item.id, v.version)} aria-label={`Restore version ${v.version}`}>Restore</button>
                          )}
                        </li>
                      ))}
                    </ul>
                    {diff && (
                      <>
                        <div className="suite-hint">Changes since version {diff.version}:</div>
                        <WorkflowDiffView diff={diff.result.diff} identical="The current copy is identical to this version." testId="version-diff" />
                      </>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
