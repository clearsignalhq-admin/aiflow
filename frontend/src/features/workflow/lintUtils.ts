import type { LintFinding, LintSeverity, PathEstimate } from '../../models/lint';

export interface LintBadge {
  severity: LintSeverity;
  count: number;
  /** Newline-separated messages, for the badge tooltip. */
  title: string;
}

const RANK: Record<LintSeverity, number> = { error: 0, warning: 1, info: 2 };

/** Groups findings by node; the badge shows the worst severity and the count. */
export function lintBadges(findings: LintFinding[]): Record<string, LintBadge> {
  const byNode: Record<string, LintFinding[]> = {};
  for (const f of findings) {
    if (!f.node_id) continue;
    (byNode[f.node_id] ??= []).push(f);
  }
  const badges: Record<string, LintBadge> = {};
  for (const [nodeId, list] of Object.entries(byNode)) {
    const severity = list.reduce<LintSeverity>((worst, f) => (RANK[f.severity] < RANK[worst] ? f.severity : worst), 'info');
    badges[nodeId] = { severity, count: list.length, title: list.map((f) => f.message).join('\n') };
  }
  return badges;
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${Number.isInteger(seconds) ? seconds : seconds.toFixed(1)} s`;
  const minutes = seconds / 60;
  return `${Number.isInteger(minutes) ? minutes : minutes.toFixed(1)} min`;
}

export function formatCost(usd: number): string {
  if (usd === 0) return '$0';
  return usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`;
}

/** One-line summary of the cheapest/slowest paths, or null when there are none. */
export function summariseEstimates(estimates: PathEstimate[]): string | null {
  if (estimates.length === 0) return null;
  const latencies = estimates.map((e) => e.latency_ms);
  const costs = estimates.map((e) => e.cost_usd);
  const range = (a: number, b: number, fmt: (n: number) => string) => (a === b ? fmt(a) : `${fmt(a)} – ${fmt(b)}`);
  const n = estimates.length;
  return `${n} path${n === 1 ? '' : 's'} · ~${range(Math.min(...latencies), Math.max(...latencies), formatDuration)} · ~${range(Math.min(...costs), Math.max(...costs), formatCost)} per run (rough estimate)`;
}
