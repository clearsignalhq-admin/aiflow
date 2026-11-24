export type FailureKind = 'error' | 'timeout' | 'empty' | 'malformed';
export type DrillVerdict = 'handled' | 'ignored' | 'halted';

export interface DrillResult {
  node_id: string;
  node_name: string;
  node_type: string;
  kind: FailureKind;
  verdict: DrillVerdict;
  detail: string;
  path: string[];
  error: string | null;
}

export interface ResilienceReport {
  baseline_status: string;
  baseline_path: string[];
  results: DrillResult[];
  summary: { handled: number; ignored: number; halted: number; total: number };
  not_reached: string[];
  skipped: number;
  notes: string[];
}

export interface Exposure {
  node_id: string;
  name: string;
  severity: 'high' | 'medium' | 'low';
  sources: { node_id: string; name: string; kind: string }[];
  sinks: { node_id: string; name: string; action: string; gated: boolean }[];
  message: string;
  advice: string;
}

export interface ExposureReport {
  exposures: Exposure[];
  llm_steps: number;
  notes: string[];
}
