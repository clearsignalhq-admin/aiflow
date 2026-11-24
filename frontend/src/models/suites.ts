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
  coverage: Coverage;
}

export type RunStatus = 'running' | 'complete' | 'cancelled' | 'failed';

export interface SuiteRunDetail {
  id: string;
  suite_id: string;
  status: RunStatus;
  case_count: number;
  seed: number;
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
