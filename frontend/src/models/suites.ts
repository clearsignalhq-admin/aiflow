export const ASSERTION_TYPES = [
  'equals', 'contains', 'exists', 'compare', 'one_of',
  'matches_schema', 'expression', 'visits_node', 'skips_node', 'max_steps',
] as const;
export type AssertionType = (typeof ASSERTION_TYPES)[number];

export const COMPARE_OPS = ['==', '!=', '<', '<=', '>', '>='] as const;

/** One deterministic check; which fields apply depends on `type` (see backend services/assertions.py). */
export interface Assertion {
  type: AssertionType;
  label?: string;
  path?: string;
  value?: unknown;
  op?: string;
  values?: unknown[];
  output_schema?: Record<string, unknown>;
  expression?: string;
  node_id?: string;
  max_steps?: number;
}

export interface SuiteCase {
  id?: string;
  name: string;
  input: Record<string, unknown>;
  assertions: Assertion[];
  tags: string[];
  seed?: number | null;
}

export interface SuiteSummary {
  id: string;
  workflow_id: string;
  name: string;
  case_count: number;
  updated_at: string;
}

export interface SuiteDetail {
  id: string;
  workflow_id: string;
  name: string;
  cases: SuiteCase[];
  created_at: string;
  updated_at: string;
}

export interface AssertionOutcome {
  index: number;
  type: string;
  label: string;
  passed: boolean;
  message: string;
}

export type CaseStatus = 'passed' | 'failed' | 'error';

export interface CaseResult {
  case_id: string;
  case_name: string;
  status: CaseStatus;
  duration_ms: number;
  /** Model calls this case made (real-model runs only). */
  llm_calls?: number;
  error?: string | null;
  error_node_id?: string | null;
  assertion_results: AssertionOutcome[];
  output?: unknown;
  path: string[];
  edges_taken: string[];
  warnings: string[];
}

export interface Coverage {
  node_visits: Record<string, number>;
  never_visited: string[];
  edges_taken: Record<string, number>;
  edges_never_taken: { source: string; target: string; label: string | null }[];
  node_failures: Record<string, number>;
}

export interface RunReport {
  total: number;
  completed: number;
  passed: number;
  failed: number;
  errors: number;
  pass_rate: number | null;
  llm_calls?: number;
  coverage: Coverage;
}

export type RunStatus = 'running' | 'complete' | 'cancelled' | 'failed';
export type LlmMode = 'mock' | 'real';

/** What a run would use, from POST /suites/{id}/runs/estimate. Nothing is reserved. */
export interface RunEstimate {
  cases: number;
  llm_mode: LlmMode;
  llm_calls_per_case_max: number;
  llm_calls_max: number;
  cost_usd_max: number;
  executions_needed: number;
  executions_remaining: number | null;
  llm_requests_remaining: number | null;
  allowed: boolean;
  reason: string | null;
  warnings: string[];
}

export interface SuiteRunDetail {
  id: string;
  suite_id: string;
  status: RunStatus;
  case_count: number;
  seed: number;
  llm_mode?: LlmMode;
  cases: { id: string; name: string }[];
  results: CaseResult[];
  report: RunReport;
  created_at: string;
  finished_at?: string | null;
  note?: string | null;
}

export interface SuiteRunSummary {
  id: string;
  suite_id: string;
  status: RunStatus;
  case_count: number;
  passed: number;
  failed: number;
  errors: number;
  created_at: string;
  finished_at?: string | null;
}

// ── Comparing two runs ───────────────────────────────────────────────────────

export type CaseChange = 'regressed' | 'fixed' | 'still_failing' | 'unchanged' | 'added' | 'removed' | 'incomplete';

export interface AssertionChange {
  label: string;
  type: string;
  base_passed: boolean | null;
  head_passed: boolean | null;
  base_message?: string | null;
  head_message?: string | null;
}

export interface CaseComparison {
  case_id: string;
  case_name: string;
  change: CaseChange;
  base_status: string | null;
  head_status: string | null;
  definition_changed: boolean;
  path_changed: boolean;
  nodes_added: string[];
  nodes_removed: string[];
  output_changed: boolean;
  assertion_changes: AssertionChange[];
  base_error?: string | null;
  head_error?: string | null;
  duration_delta_ms: number | null;
  llm_calls_delta: number | null;
}

export interface FieldChange { field: string; before: unknown; after: unknown }
export interface NodeChange { node_id: string; name: string; change: 'added' | 'removed' | 'modified'; fields: FieldChange[] }
export interface EdgeChange { source: string; target: string; source_name: string; target_name: string; label: string | null; change: 'added' | 'removed' }

export interface RunSide {
  id: string;
  created_at: string;
  status: string;
  llm_mode: LlmMode;
  seed: number;
  case_count: number;
  completed: number;
  passed: number;
  failed: number;
  errors: number;
  pass_rate: number | null;
  llm_calls: number;
  total_duration_ms: number;
}

export interface RunComparison {
  base: RunSide;
  head: RunSide;
  verdict: 'regression' | 'improvement' | 'no_change';
  summary: {
    regressed: number; fixed: number; still_failing: number; unchanged: number;
    added: number; removed: number; incomplete: number; pass_rate_delta: number | null;
  };
  cases: CaseComparison[];
  workflow: { nodes: NodeChange[]; edges: EdgeChange[]; changed: boolean };
  coverage: {
    nodes_newly_visited: string[]; nodes_no_longer_visited: string[];
    edges_newly_taken: string[]; edges_no_longer_taken: string[];
  };
  warnings: string[];
}
