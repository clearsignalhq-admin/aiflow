import { API_BASE } from '../config';
import { formatApiError } from '../utils/apiError';
import type { Workflow } from '../models/workflow';
import type {
  CloudWorkflowDetail, CloudWorkflowSummary, SharedWorkflow, VersionDiff, VersionSummary,
} from '../models/cloud';

export class CloudApiError extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.status = status;
  }
}

async function call<T>(token: string | undefined, path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api${path}`, {
      method: init.method ?? 'GET',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch {
    throw new CloudApiError('Could not reach backend. Is it running on port 8000?');
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null) as unknown;
  if (!res.ok) throw new CloudApiError(formatApiError(data, res.status), res.status);
  return data as T;
}

const base = '/cloud/workflows';

export const cloudApi = {
  list: (token: string | undefined) => call<CloudWorkflowSummary[]>(token, base),
  get: (token: string | undefined, id: string) => call<CloudWorkflowDetail>(token, `${base}/${id}`),
  create: (token: string | undefined, name: string, workflow: Workflow, label?: string) =>
    call<CloudWorkflowDetail>(token, base, { method: 'POST', body: { name, workflow, label: label || null } }),
  save: (token: string | undefined, id: string, workflow: Workflow, label?: string) =>
    call<CloudWorkflowDetail>(token, `${base}/${id}`, { method: 'PUT', body: { workflow, label: label || null } }),
  remove: (token: string | undefined, id: string) => call<void>(token, `${base}/${id}`, { method: 'DELETE' }),
  versions: (token: string | undefined, id: string) => call<VersionSummary[]>(token, `${base}/${id}/versions`),
  diff: (token: string | undefined, id: string, baseVersion: number) =>
    call<VersionDiff>(token, `${base}/${id}/diff?base=${baseVersion}`),
  restore: (token: string | undefined, id: string, version: number) =>
    call<CloudWorkflowDetail>(token, `${base}/${id}/versions/${version}/restore`, { method: 'POST' }),
  share: (token: string | undefined, id: string) =>
    call<{ share_token: string | null }>(token, `${base}/${id}/share`, { method: 'POST' }),
  unshare: (token: string | undefined, id: string) =>
    call<{ share_token: string | null }>(token, `${base}/${id}/share`, { method: 'DELETE' }),
};

/** Public: no sign-in, read only. */
export const sharedApi = {
  get: (shareToken: string) => call<SharedWorkflow>(undefined, `/shared/${encodeURIComponent(shareToken)}`),
};

export function shareUrl(shareToken: string): string {
  return `${window.location.origin}/shared/${shareToken}`;
}
