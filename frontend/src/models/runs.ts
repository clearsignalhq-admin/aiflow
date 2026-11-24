import type { Workflow } from './workflow';
import type { ExecutionTrace, SimulationEvaluation, SimulationSettings } from './simulation';

/** A persisted simulation run, as listed by GET /api/runs. */
export interface RunSummary {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: ExecutionTrace['status'];
  step_count: number;
  truncated: boolean;
  evaluation_score: number | null;
  created_at: string;
}

/** A persisted run with everything needed to replay it (GET /api/runs/{id}). */
export interface RunDetail extends Omit<RunSummary, 'evaluation_score'> {
  settings: SimulationSettings;
  input: Record<string, unknown>;
  /** The workflow as it was when the run happened. */
  workflow: Workflow;
  trace: ExecutionTrace;
  evaluation: SimulationEvaluation | null;
}
