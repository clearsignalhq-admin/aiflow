import type { Workflow } from './workflow';

/** A suggested change: operations applied together or not at all (the server owns their meaning). */
export interface SuggestedChange {
  id: string;
  title: string;
  rationale: string;
  source: string;
  ops: Record<string, unknown>[];
  summary: string[];
  touches: string[];
}

export interface SuggestResult {
  summary: string;
  changes: SuggestedChange[];
  discarded: string[];
}

export interface ApplyResult {
  workflow: Workflow;
  applied: string[];
  skipped: { id: string; reason: string }[];
  added_node_ids: string[];
}
