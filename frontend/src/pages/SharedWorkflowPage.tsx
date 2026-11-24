import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Background, Controls, ReactFlow, ReactFlowProvider } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { SharedWorkflow } from '../models/cloud';
import { sharedApi } from '../services/cloud';
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

  useEffect(() => {
    let cancelled = false;
    sharedApi.get(token)
      .then((s) => { if (!cancelled) setShared(s); })
      .catch((err: unknown) => { if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load this workflow.'); });
    return () => { cancelled = true; };
  }, [token]);

  const graph = useMemo(() => (shared ? workflowToReactFlow(shared.workflow) : null), [shared]);

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
          <Link className="btn btn-primary" to="/login">Sign in to build your own</Link>
        </div>
      </header>
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
