export type LintSeverity = 'error' | 'warning' | 'info';

export interface LintFinding {
  rule_id: string;
  severity: LintSeverity;
  node_id: string | null;
  message: string;
  fix_hint: string;
}

/** Rough per-path latency/cost estimate from fixed node-type heuristics. */
export interface PathEstimate {
  node_ids: string[];
  node_names: string[];
  latency_ms: number;
  cost_usd: number;
}

export interface LintResult {
  findings: LintFinding[];
  estimates: PathEstimate[];
}
