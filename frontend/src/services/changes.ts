import { API_BASE } from '../config';
import { formatApiError } from '../utils/apiError';
import type { Workflow } from '../models/workflow';
import type { ApplyResult, SuggestedChange, SuggestResult } from '../models/changes';

export class ChangeApiError extends Error {}

async function post<T>(token: string | undefined, path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/workflows/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ChangeApiError('Could not reach backend. Is it running on port 8000?');
  }
  const data = await res.json().catch(() => null) as unknown;
  if (!res.ok) throw new ChangeApiError(formatApiError(data, res.status));
  return data as T;
}

export const changeApi = {
  /** Deterministic fixes for what the checks flag. Free. */
  fixes: async (token: string | undefined, workflow: Workflow) =>
    (await post<{ changes: SuggestedChange[] }>(token, 'fixes', { workflow })).changes,

  /** AI proposals for an instruction. Uses one AI request; nothing is applied. */
  suggest: (token: string | undefined, workflow: Workflow, instruction: string) =>
    post<SuggestResult>(token, 'suggest', { workflow, instruction }),

  apply: (token: string | undefined, workflow: Workflow, changes: SuggestedChange[]) =>
    post<ApplyResult>(token, 'apply-changes', { workflow, changes }),
};
