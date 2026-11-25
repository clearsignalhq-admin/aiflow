import type { SuiteRunSummary } from '../../../models/suites';
import { percent } from './format';

const MAX_POINTS = 12;
const W = 280;
const H = 56;
const PAD = 6;

interface Props {
  /** Newest first, as the server lists them. */
  runs: SuiteRunSummary[];
}

/** Pass rate of the last finished runs, oldest to newest, so a slow decline is visible at a glance. */
export function PassRateTrend({ runs }: Props) {
  const rates = runs
    .filter((r) => r.status === 'complete' && r.passed + r.failed + r.errors > 0)
    .slice(0, MAX_POINTS)
    .reverse()
    .map((r) => r.passed / (r.passed + r.failed + r.errors));
  if (rates.length < 2) return null;

  const x = (i: number) => PAD + (i * (W - 2 * PAD)) / (rates.length - 1);
  const y = (rate: number) => H - PAD - rate * (H - 2 * PAD);
  const last = rates[rates.length - 1];
  const delta = Math.round((last - rates[rates.length - 2]) * 100);
  const summary = rates.map((r) => percent(r)).join(', ');

  return (
    <div className="trend" data-testid="pass-rate-trend">
      <div className="suite-coverage-title">Pass rate over time</div>
      <svg className="trend-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Pass rate over the last ${rates.length} runs, oldest to newest: ${summary}`}>
        <line x1={PAD} x2={W - PAD} y1={y(1)} y2={y(1)} className="trend-grid" />
        <line x1={PAD} x2={W - PAD} y1={y(0)} y2={y(0)} className="trend-grid" />
        <polyline points={rates.map((r, i) => `${x(i)},${y(r)}`).join(' ')} className="trend-line" fill="none" />
        {rates.map((r, i) => (
          <circle key={i} cx={x(i)} cy={y(r)} r={i === rates.length - 1 ? 4 : 2.5} className={r < 1 ? 'trend-dot trend-dot--low' : 'trend-dot'} />
        ))}
      </svg>
      <div className="suite-hint" data-testid="trend-summary">
        Latest {percent(last)}
        {delta === 0 ? ' · same as the run before' : delta > 0 ? ` · up ${delta} points on the run before` : ` · down ${-delta} points on the run before`}
      </div>
    </div>
  );
}
