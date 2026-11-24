import { useState } from 'react';
import type { CaseComparison, RunComparison as Comparison, RunSide } from '../../../models/suites';
import { percent } from './format';
import { WorkflowDiffView } from '../WorkflowDiffView';

interface Props {
  comparison: Comparison;
  /** node id → display name for the current workflow (ids are shown when a name is unknown) */
  nodeNames: Record<string, string>;
}

const VERDICT_TEXT = {
  regression: 'Regression',
  improvement: 'Improvement',
  no_change: 'No change',
} as const;

const CHANGE_LABEL: Record<CaseComparison['change'], string> = {
  regressed: 'Regressed',
  fixed: 'Fixed',
  still_failing: 'Still failing',
  unchanged: 'Unchanged',
  added: 'New case',
  removed: 'Removed case',
  incomplete: 'Not run in both',
};

function points(delta: number | null): string {
  if (delta === null) return '—';
  const pts = Math.round(delta * 100);
  return `${pts > 0 ? '+' : ''}${pts} points`;
}

function SideLine({ label, side }: { label: string; side: RunSide }) {
  return (
    <div className="cmp-side">
      <strong>{label}</strong> {new Date(side.created_at).toLocaleString()} · {percent(side.pass_rate)} passed ({side.passed}/{side.completed})
      {side.llm_mode === 'real' ? ` · real model, ${side.llm_calls} calls` : ' · simulated'}
    </div>
  );
}

function CaseRow({ c, nodeNames }: { c: CaseComparison; nodeNames: Record<string, string> }) {
  const [open, setOpen] = useState(c.change === 'regressed' || c.change === 'fixed');
  const name = (id: string) => nodeNames[id] ?? id;
  const hasDetail = c.assertion_changes.length > 0 || c.path_changed || c.output_changed || !!c.head_error || !!c.base_error || c.definition_changed;
  return (
    <li className={`cmp-case cmp-case--${c.change}`} data-testid="cmp-case">
      <button className="suite-result-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className={`cmp-badge cmp-badge--${c.change}`}>{CHANGE_LABEL[c.change]}</span>
        <span className="suite-result-name">{c.case_name}</span>
        <span className="suite-result-time">{c.base_status ?? '—'} → {c.head_status ?? '—'}</span>
      </button>
      {open && (
        <div className="suite-result-body">
          {c.definition_changed && <div className="suite-hint">This test case was edited between the runs.</div>}
          {c.assertion_changes.map((a, i) => (
            <div key={i} className={a.head_passed === false ? 'suite-outcome--fail' : 'suite-outcome--pass'}>
              {a.head_passed === false ? '✗' : a.head_passed === true ? '✓' : '·'} <strong>{a.label}</strong>:
              {' '}{a.base_passed === null ? 'new check' : a.base_passed ? 'passed' : 'failed'} → {a.head_passed === null ? 'removed' : a.head_passed ? 'passed' : 'failed'}
              {a.head_message && a.head_passed === false && <> — {a.head_message}</>}
            </div>
          ))}
          {c.path_changed && (
            <div className="suite-hint">
              Path changed
              {c.nodes_added.length > 0 && <> · now runs: {c.nodes_added.map(name).join(', ')}</>}
              {c.nodes_removed.length > 0 && <> · no longer runs: {c.nodes_removed.map(name).join(', ')}</>}
            </div>
          )}
          {c.output_changed && <div className="suite-hint">The output changed.</div>}
          {c.head_error && <div className="suite-result-error">Now: {c.head_error}</div>}
          {c.base_error && !c.head_error && <div className="suite-hint">Before: {c.base_error}</div>}
          {!hasDetail && <div className="suite-hint">Nothing else differs.</div>}
          {(c.duration_delta_ms !== null && c.duration_delta_ms !== 0) || c.llm_calls_delta ? (
            <div className="suite-hint">
              {c.duration_delta_ms ? `${c.duration_delta_ms > 0 ? '+' : ''}${c.duration_delta_ms} ms` : ''}
              {c.llm_calls_delta ? ` · ${c.llm_calls_delta > 0 ? '+' : ''}${c.llm_calls_delta} model calls` : ''}
            </div>
          ) : null}
        </div>
      )}
    </li>
  );
}

export function RunComparison({ comparison: c, nodeNames }: Props) {
  const [showUnchanged, setShowUnchanged] = useState(false);
  const s = c.summary;
  const name = (id: string) => nodeNames[id] ?? id;
  const changed = c.cases.filter((x) => x.change !== 'unchanged');
  const unchanged = c.cases.filter((x) => x.change === 'unchanged');

  return (
    <div className="cmp" aria-label="Run comparison">
      <div className={`cmp-verdict cmp-verdict--${c.verdict}`} data-testid="cmp-verdict">
        <span className="cmp-verdict-title">{VERDICT_TEXT[c.verdict]}</span>
        <span>
          {percent(c.base.pass_rate)} → {percent(c.head.pass_rate)} passed ({points(s.pass_rate_delta)})
        </span>
      </div>
      <div className="suite-counts" data-testid="cmp-counts">
        <span className="suite-count--fail">{s.regressed} regressed</span>
        {' · '}<span className="suite-count--pass">{s.fixed} fixed</span>
        {' · '}{s.still_failing} still failing · {s.unchanged} unchanged
        {s.added > 0 && <> · {s.added} new</>}
        {s.removed > 0 && <> · {s.removed} removed</>}
        {s.incomplete > 0 && <> · {s.incomplete} not run in both</>}
      </div>
      <SideLine label="Earlier" side={c.base} />
      <SideLine label="This run" side={c.head} />

      {c.warnings.length > 0 && (
        <ul className="validation-list validation-list--warnings" data-testid="cmp-warnings">
          {c.warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}

      {changed.length > 0 && (
        <>
          <div className="suite-coverage-title">Cases that changed</div>
          <ul className="suite-results">{changed.map((x) => <CaseRow key={x.case_id} c={x} nodeNames={nodeNames} />)}</ul>
        </>
      )}
      {changed.length === 0 && <div className="suite-hint">Every case came out the same in both runs.</div>}
      {unchanged.length > 0 && (
        <>
          <button className="btn btn-ghost" onClick={() => setShowUnchanged((v) => !v)}>
            {showUnchanged ? 'Hide' : 'Show'} {unchanged.length} unchanged case{unchanged.length === 1 ? '' : 's'}
          </button>
          {showUnchanged && <ul className="suite-results">{unchanged.map((x) => <CaseRow key={x.case_id} c={x} nodeNames={nodeNames} />)}</ul>}
        </>
      )}

      <div className="suite-coverage-title">What changed in the workflow</div>
      <WorkflowDiffView diff={c.workflow} identical="The workflow is identical in both runs." testId="cmp-workflow" />

      {(c.coverage.nodes_no_longer_visited.length > 0 || c.coverage.nodes_newly_visited.length > 0) && (
        <div className="suite-hint" data-testid="cmp-coverage">
          {c.coverage.nodes_no_longer_visited.length > 0 && <>No case reaches any more: {c.coverage.nodes_no_longer_visited.map(name).join(', ')}. </>}
          {c.coverage.nodes_newly_visited.length > 0 && <>Newly reached: {c.coverage.nodes_newly_visited.map(name).join(', ')}.</>}
        </div>
      )}
    </div>
  );
}
