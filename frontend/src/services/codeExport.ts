import { API_BASE } from '../config';
import { formatApiError } from '../utils/apiError';
import type { Workflow } from '../models/workflow';

export type ExportTarget = 'langgraph' | 'python' | 'mcp';

export interface ExportedProject {
  blob: Blob;
  filename: string;
}

export interface TargetInfo {
  id: ExportTarget;
  label: string;
  description: string;
  /** Whether a test suite can be turned into generated tests for this target. */
  supportsTests: boolean;
  /** What to run after unzipping. */
  nextSteps: string;
  /** What to know about how it differs from the AiFlow simulator (or from the other targets). */
  notes: string[];
}

const STEPS_NOTE = "API, DATABASE and knowledge-search steps make real requests, queries and searches (secrets come from environment variables). TOOL and TRANSFORM steps need your code in integrations.py. `--mock` returns fixtures for everything.";

/** Keep in sync with backend/app/services/exporters.py (TARGETS) and the generated READMEs. */
export const EXPORT_TARGETS: TargetInfo[] = [
  {
    id: 'langgraph',
    label: 'LangGraph (Python)',
    description: 'The whole workflow as a LangGraph project: graph, steps, routing, human-review pauses, command-line runner and tests.',
    supportsTests: true,
    nextSteps: 'pip install -r requirements.txt\npython main.py --mock\npytest',
    notes: [
      "Each step's output is merged into the running data, so later steps can use earlier results.",
      STEPS_NOTE,
      'If a decision matches none of its branches the exported code stops with an error instead of exploring every branch.',
    ],
  },
  {
    id: 'python',
    label: 'Plain Python',
    description: 'The whole workflow with no framework: a small engine and the same steps and tests. Easiest to read, change and embed.',
    supportsTests: true,
    nextSteps: 'pip install -r requirements.txt\npython main.py --mock\npytest',
    notes: [
      "Each step's output is merged into the running data, and each step runs at most once per run (loops are not repeated).",
      STEPS_NOTE,
      'A human review asks in the terminal (or through a callback); a run cannot be paused in one process and resumed in another.',
    ],
  },
  {
    id: 'mcp',
    label: 'MCP tools',
    description: "The workflow's tool, API, database and knowledge-search steps as an MCP server that Claude Desktop, IDEs and agents can call.",
    supportsTests: false,
    nextSteps: 'pip install -r requirements.txt\npytest\nAIFLOW_MOCK=1 python server.py',
    notes: [
      'Only TOOL, API, DATABASE and knowledge-search steps become tools; AI-model steps and decisions are part of the workflow, not tools.',
      "A step's input schema (data contract) becomes the tool's input schema; otherwise it comes from the {{fields}} the step uses.",
      'Secrets are read from environment variables; set them in your MCP client config. Test suites are not used for this target.',
    ],
  },
];

function filenameFrom(disposition: string | null, fallback: string): string {
  const match = disposition ? /filename="?([^";]+)"?/i.exec(disposition) : null;
  return match ? match[1] : fallback;
}

/**
 * Ask the backend for a runnable project (a zip) for `target`. Pass a suite id to include that suite's
 * cases as generated pytest tests (not available for the MCP target). Throws an Error with a readable message.
 */
export async function exportProject(
  token: string | undefined,
  workflow: Workflow,
  target: ExportTarget = 'langgraph',
  suiteId?: string,
): Promise<ExportedProject> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/workflows/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ workflow, target, ...(suiteId ? { suite_id: suiteId } : {}) }),
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
    filename: filenameFrom(res.headers.get('Content-Disposition'), `workflow-${target}.zip`),
  };
}

// ── Import ───────────────────────────────────────────────────────────────────

export const MAX_IMPORT_FILES = 20;
export const MAX_IMPORT_FILE_CHARS = 200_000;

export interface ImportedCode {
  workflow: Workflow;
  warnings: string[];
  /** "exact" when the upload was an AiFlow export and the workflow was restored as is. */
  mode: 'exact' | 'inferred';
}

/** Read the text of the files a user picked. Rejects files that are too many or too large before anything is sent. */
export function readFiles(files: File[]): Promise<Record<string, string>> {
  if (files.length > MAX_IMPORT_FILES) return Promise.reject(new Error(`Choose at most ${MAX_IMPORT_FILES} files.`));
  const tooBig = files.find((f) => f.size > MAX_IMPORT_FILE_CHARS);
  if (tooBig) return Promise.reject(new Error(`${tooBig.name} is too large (max ${MAX_IMPORT_FILE_CHARS / 1000} KB per file).`));
  return Promise.all(files.map((file) => new Promise<[string, string]>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve([file.name, String(reader.result ?? '')]);
    reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
    reader.readAsText(file);
  }))).then((pairs) => Object.fromEntries(pairs));
}

/** Parse LangGraph code into a workflow. The server only reads the code; it never runs it. */
export async function importLangGraph(token: string | undefined, files: Record<string, string>): Promise<ImportedCode> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/workflows/import/langgraph`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ files }),
    });
  } catch {
    throw new Error('Could not reach backend. Is it running on port 8000?');
  }
  const data = await res.json().catch(() => null) as { workflow?: Workflow; warnings?: string[]; mode?: 'exact' | 'inferred' } | null;
  if (!res.ok || !data?.workflow) throw new Error(formatApiError(data, res.status));
  return { workflow: data.workflow, warnings: data.warnings ?? [], mode: data.mode ?? 'inferred' };
}
