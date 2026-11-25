import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Background, Controls, ReactFlow, ReactFlowProvider } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { SharedWorkflow } from '../models/cloud';
import { useAuth } from '../context/AuthContext';
import { cloudApi, sharedApi } from '../services/cloud';
import { workflowToReactFlow } from '../features/workflow/WorkflowAdapter';
import { WorkflowNodeComponent } from '../features/workflow/nodes/WorkflowNodeComponent';
import { downloadText } from '../utils/download';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const nodeTypes = { workflowNode: WorkflowNodeComponent as any };

/** Public, read-only view of a shared workflow. No sign-in; nothing here can change it. */
export default function SharedWorkflowPage() {
  const { token = '' } = useParams();
  const [shared, setShared] = useState<SharedWorkflow | null>(null);
  const [error, setError] = useState('');
  const { session } = useAuth();
  const [copy, setCopy] = useState<{ kind: 'idle' | 'saving' } | { kind: 'done'; name: string } | { kind: 'error'; message: string }>({ kind: 'idle' });

  useEffect(() => {
    let cancelled = false;
    sharedApi.get(token)
      .then((s) => { if (!cancelled) setShared(s); })
      .catch((err: unknown) => { if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load this workflow.'); });
    return () => { cancelled = true; };
  }, [token]);

  const graph = useMemo(() => (shared ? workflowToReactFlow(shared.workflow) : null), [shared]);

  const saveCopy = async () => {
    if (!shared || !session) return;
    const name = `${shared.name} (copy)`.slice(0, 100);
    setCopy({ kind: 'saving' });
    try {
      await cloudApi.create(session.access_token, name, shared.workflow, 'Copied from a shared link');
      setCopy({ kind: 'done', name });
    } catch (err) {
      setCopy({ kind: 'error', message: err instanceof Error ? err.message : 'Could not save the copy.' });
    }
  };

  if (error) {
    return (
      <div className="shared-page shared-page--message">
        <h1>Workflow not available</h1>
        <p role="alert">{error}</p>
        <Link to="/">Go to AiFlow</Link>
      </div>
    );
  }
  if (!shared || !graph) return <div className="shared-page shared-page--message">Loading…</div>;

  return (
    <div className="shared-page">
      <header className="shared-header">
        <div>
          <Link to="/" className="shared-brand">⬡ AiFlow</Link>
          <h1 className="shared-title">{shared.name}</h1>
          <div className="suite-hint">Shared read-only · {shared.workflow.nodes.length} steps{shared.workflow.description ? ` · ${shared.workflow.description}` : ''}</div>
        </div>
        <div className="shared-actions">
          <button className="btn btn-ghost" onClick={() => downloadText(JSON.stringify(shared.workflow, null, 2), `${shared.name.replace(/[^a-zA-Z0-9-_]+/g, '-').toLowerCase() || 'workflow'}.json`, 'application/json')}>
            Download JSON
          </button>
          {session ? (
            copy.kind === 'done'
              ? <Link className="btn btn-primary" to="/app">Open the editor</Link>
              : <button className="btn btn-primary" onClick={() => void saveCopy()} disabled={copy.kind === 'saving'}>
                  {copy.kind === 'saving' ? 'Saving…' : 'Save a copy to my cloud workflows'}
                </button>
          ) : (
            <Link className="btn btn-primary" to="/login">Sign in to build your own</Link>
          )}
        </div>
      </header>
      {copy.kind === 'done' && <div className="suite-hint shared-note" role="status">Saved “{copy.name}”. Open it from File, then Cloud workflows, in the editor.</div>}
      {copy.kind === 'error' && <div className="modal-error shared-note" role="alert">{copy.message}</div>}
      <div className="shared-canvas" data-testid="shared-canvas">
        <ReactFlowProvider>
          <ReactFlow
            nodes={graph.nodes}
            edges={graph.edges}
            nodeTypes={nodeTypes}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background />
            <Controls showInteractive={false} />
          </ReactFlow>
        </ReactFlowProvider>
      </div>
    </div>
  );
}
