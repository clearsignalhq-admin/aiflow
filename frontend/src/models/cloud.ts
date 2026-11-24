import type { Workflow } from './workflow';
import type { EdgeChange, NodeChange } from './suites';

export interface CloudWorkflowSummary {
  id: string;
  name: string;
  version_count: number;
  shared: boolean;
  updated_at: string;
}

export interface CloudWorkflowDetail extends CloudWorkflowSummary {
  workflow: Workflow;
  share_token: string | null;
  /** False when a save changed nothing and so added no version. */
  new_version: boolean;
}

export interface VersionSummary {
  version: number;
  label: string | null;
  created_at: string;
  node_count: number;
  edge_count: number;
}

export interface WorkflowDiff {
  nodes: NodeChange[];
  edges: EdgeChange[];
  changed: boolean;
}

export interface VersionDiff {
  base_version: number;
  head_version: number | null;
  diff: WorkflowDiff;
}

export interface SharedWorkflow {
  name: string;
  workflow: Workflow;
  shared_at: string | null;
}
