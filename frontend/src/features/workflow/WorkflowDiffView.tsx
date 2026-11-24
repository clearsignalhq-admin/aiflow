import type { WorkflowDiff } from '../../models/cloud';

function show(value: unknown): string {
  if (value === null || value === undefined) return '(none)';
  return typeof value === 'string' ? value : JSON.stringify(value);
}

interface Props {
  diff: WorkflowDiff;
  /** Shown when nothing differs. */
  identical: string;
  testId?: string;
}

/** Steps and connections that were added, removed or edited, with before/after values for edited settings. */
export function WorkflowDiffView({ diff, identical, testId }: Props) {
  if (!diff.changed) {
    return <div className="suite-hint" data-testid={testId}>{identical}</div>;
  }
  return (
    <div className="cmp-workflow" data-testid={testId}>
      {diff.nodes.map((n) => (
        <div key={n.node_id}>
          <strong>{n.change === 'added' ? 'Added' : n.change === 'removed' ? 'Removed' : 'Edited'}</strong> step “{n.name}”
          {n.fields.map((f) => (
            <div key={f.field} className="cmp-field">
              <code>{f.field}</code>: <span className="cmp-before">{show(f.before)}</span> → <span className="cmp-after">{show(f.after)}</span>
            </div>
          ))}
        </div>
      ))}
      {diff.edges.map((e) => (
        <div key={`${e.change}-${e.source}-${e.target}-${e.label}`}>
          <strong>{e.change === 'added' ? 'Added' : 'Removed'}</strong> connection {e.source_name} → {e.target_name}{e.label ? ` (${e.label})` : ''}
        </div>
      ))}
    </div>
  );
}
