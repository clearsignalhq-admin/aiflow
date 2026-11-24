import { API_BASE } from '../config';
import { formatApiError } from '../utils/apiError';
import type { Workflow } from '../models/workflow';

export interface ExportedProject {
  blob: Blob;
  filename: string;
}

/** What differs between the exported project and the AiFlow simulator (kept in sync with the backend README). */
export const EXPORT_NOTES = [
  'Each step\'s output is merged into the running data, so later steps can use earlier results.',
  'TOOL, API, DATABASE, RAG and TRANSFORM steps are stubs that return fixtures until you implement them in integrations.py.',
  'If a decision matches none of its branches the exported code stops with an error instead of exploring every branch.',
];

function filenameFrom(disposition: string | null, fallback: string): string {
  const match = disposition ? /filename="?([^";]+)"?/i.exec(disposition) : null;
  return match ? match[1] : fallback;
}

/**
 * Ask the backend for a runnable LangGraph project (a zip). Pass a suite id to include that suite's
 * cases as generated pytest tests. Throws an Error with a readable message on failure.
 */
export async function exportLangGraph(
  token: string | undefined,
  workflow: Workflow,
  suiteId?: string,
): Promise<ExportedProject> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/workflows/export/langgraph`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ workflow, ...(suiteId ? { suite_id: suiteId } : {}) }),
    });
  } catch {
    throw new Error('Could not reach backend. Is it running on port 8000?');
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null) as unknown;
    throw new Error(formatApiError(body, res.status));
  }
  return {
    blob: await res.blob(),
    filename: filenameFrom(res.headers.get('Content-Disposition'), 'workflow-langgraph.zip'),
  };
}
