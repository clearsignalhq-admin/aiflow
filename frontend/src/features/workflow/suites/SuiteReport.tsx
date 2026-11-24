import { useState } from 'react';
import type { CaseResult, SuiteRunDetail } from '../../../models/suites';
import { percent } from './format';

interface Props {
  run: SuiteRunDetail;
  /** node id → display name, from the workflow the run used or the current one */
  nodeNames: Record<string, string>;
}

const ICON = { passed: '✓', failed: '✗', error: '!' } as const;

function ResultRow({ result, nodeNames }: { result: CaseResult; nodeNames: Record<string, string> }) {
  const [open, setOpen] = useState(result.status !== 'passed');
  const name = (id: string) => nodeNames[id] ?? id;
  return (
    <li className={`suite-result suite-result--${result.status}`} data-testid="suite-result">
      <button className="suite-result-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="suite-result-icon" aria-hidden="true">{ICON[result.status]}</span>
        <span className="suite-result-name">{result.case_name}</span>
        <span className="suite-result-status">{result.status}</span>
        <span className="suite-result-time">{result.duration_ms} ms</span>
      </button>
      {open && (
        <div className="suite-result-body">
          {result.error && <div className="suite-result-error">Error{result.error_node_id ? ` at ${name(result.error_node_id)}` : ''}: {result.error}</div>}
          {result.assertion_results.length === 0 && !result.error && (
            <div className="suite-hint">No checks defined — passes when the workflow completes.</div>
          )}
          <ul className="suite-outcomes">
            {result.assertion_results.map((o) => (
              <li key={o.index} className={o.passed ? 'suite-outcome--pass' : 'suite-outcome--fail'}>
                {o.passed ? '✓' : '✗'} <strong>{o.label}</strong> — {o.message}
              </li>
            ))}
          </ul>
          {result.path.length > 0 && <div className="suite-hint">Path: {result.path.map(name).join(' → ')}</div>}
          {result.warnings.length > 0 && <div className="suite-hint">Warnings: {result.warnings.join(' · ')}</div>}
          {result.output !== undefined && result.output !== null && (
            <details className="suite-output">
              <summary>Output</summary>
              <pre className="trace-step-json">{JSON.stringify(result.output, null, 2)}</pre>
            </details>
          )}
        </div>
      )}
    </li>
  );
}

export function SuiteReport({ run, nodeNames }: Props) {
  const name = (id: string) => nodeNames[id] ?? id;
  const results = run.results;
  const passed = results.filter((r) => r.status === 'passed').length;
  const failed = results.filter((r) => r.status === 'failed').length;
  const errors = results.filter((r) => r.status === 'error').length;
  const pending = Math.max(0, run.case_count - results.length);
  const rate = results.length ? passed / results.length : null;
  const finished = run.status !== 'running';
  const coverage = run.report.coverage;
  const hotspots = Object.entries(coverage.node_failures).sort((a, b) => b[1] - a[1]).slice(0, 5);

  return (
    <div className="suite-report" aria-label="Test run results">
      <div className="suite-summary">
        <span className={`suite-rate${rate === 1 ? ' suite-rate--good' : rate !== null && rate < 1 ? ' suite-rate--bad' : ''}`} data-testid="pass-rate">
          {percent(rate)}
        </span>
        <span className="suite-counts">
          <span className="suite-count--pass">{passed} passed</span>
          {' · '}<span className="suite-count--fail">{failed} failed</span>
          {' · '}<span className="suite-count--error">{errors} error{errors === 1 ? '' : 's'}</span>
          {pending > 0 && <>{' · '}{pending} pending</>}
        </span>
        <span className={`trace-status trace-status--${run.status === 'complete' ? 'complete' : run.status === 'running' ? 'running' : 'error'}`}>{run.status}</span>
      </div>

      {run.note && <div className="suite-result-error" role="note">{run.note}</div>}

      <div className="suite-progress" role="progressbar" aria-valuemin={0} aria-valuemax={run.case_count} aria-valuenow={results.length}>
        <div className="suite-progress-bar" style={{ width: `${run.case_count ? (results.length / run.case_count) * 100 : 0}%` }} />
      </div>

      <ul className="suite-results">
        {results.map((r) => <ResultRow key={r.case_id} result={r} nodeNames={nodeNames} />)}
      </ul>

      {finished && results.length > 0 && (
        <div className="suite-coverage">
          <div className="suite-coverage-title">Coverage</div>
          {coverage.never_visited.length === 0 && coverage.edges_never_taken.length === 0 ? (
            <div className="suite-hint">Every node and branch was exercised by at least one case.</div>
          ) : (
            <>
              {coverage.never_visited.length > 0 && (
                <div data-testid="never-visited">
                  <strong>Never executed:</strong> {coverage.never_visited.map(name).join(', ')}
                </div>
              )}
              {coverage.edges_never_taken.length > 0 && (
                <div data-testid="never-taken">
                  <strong>Branches never taken:</strong>
                  <ul>
                    {coverage.edges_never_taken.map((e) => (
                      <li key={`${e.source}→${e.target}`}>
                        {name(e.source)} → {name(e.target)}{e.label ? ` (${e.label})` : ''}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
          {hotspots.length > 0 && (
            <div data-testid="hotspots">
              <strong>Failures involve:</strong> {hotspots.map(([id, n]) => `${name(id)} (${n})`).join(', ')}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
