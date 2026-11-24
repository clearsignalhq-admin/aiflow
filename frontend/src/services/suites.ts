import { API_BASE } from '../config';
import { formatApiError } from '../utils/apiError';
import type { Workflow } from '../models/workflow';
import type {
  CaseResult, LlmMode, RunComparison, RunEstimate, SuiteCase, SuiteDetail, SuiteRunDetail, SuiteRunSummary, SuiteSummary,
} from '../models/suites';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function call<T>(token: string | undefined, path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...(init.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, 'Could not reach backend. Is it running on port 8000?');
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null) as unknown;
  if (!res.ok) throw new ApiError(res.status, formatApiError(data, res.status));
  return data as T;
}

const body = (value: unknown) => ({ body: JSON.stringify(value) });

export const suiteApi = {
  list: (token: string | undefined, workflowId: string) =>
    call<{ suites: SuiteSummary[] }>(token, `/suites?workflow_id=${encodeURIComponent(workflowId)}`).then((r) => r.suites),

  get: (token: string | undefined, suiteId: string) => call<SuiteDetail>(token, `/suites/${suiteId}`),

  create: (token: string | undefined, workflowId: string, name: string, cases: SuiteCase[]) =>
    call<SuiteDetail>(token, '/suites', { method: 'POST', ...body({ name, workflow_id: workflowId, cases }) }),

  update: (token: string | undefined, suiteId: string, name: string, cases: SuiteCase[]) =>
    call<SuiteDetail>(token, `/suites/${suiteId}`, { method: 'PUT', ...body({ name, cases }) }),

  remove: (token: string | undefined, suiteId: string) =>
    call<void>(token, `/suites/${suiteId}`, { method: 'DELETE' }),

  createRun: (token: string | undefined, suiteId: string, workflow: Workflow, seed = 0, llmMode: LlmMode = 'mock') =>
    call<SuiteRunDetail>(token, `/suites/${suiteId}/runs`, { method: 'POST', ...body({ workflow, seed, llm_mode: llmMode }) }),

  estimateRun: (token: string | undefined, suiteId: string, workflow: Workflow, llmMode: LlmMode) =>
    call<RunEstimate>(token, `/suites/${suiteId}/runs/estimate`, { method: 'POST', ...body({ workflow, llm_mode: llmMode }) }),

  runCase: (token: string | undefined, runId: string, caseId: string) =>
    call<CaseResult>(token, `/suite-runs/${runId}/cases/${caseId}/run`, { method: 'POST' }),

  getRun: (token: string | undefined, runId: string) => call<SuiteRunDetail>(token, `/suite-runs/${runId}`),

  cancelRun: (token: string | undefined, runId: string) =>
    call<SuiteRunDetail>(token, `/suite-runs/${runId}/cancel`, { method: 'POST' }),

  compareRuns: (token: string | undefined, baseId: string, headId: string) =>
    call<RunComparison>(token, `/suite-runs/compare?base=${encodeURIComponent(baseId)}&head=${encodeURIComponent(headId)}`),

  listRuns: (token: string | undefined, suiteId: string) =>
    call<{ runs: SuiteRunSummary[] }>(token, `/suites/${suiteId}/runs?limit=10`).then((r) => r.runs),
};
