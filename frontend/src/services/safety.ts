import { API_BASE } from '../config';
import { formatApiError } from '../utils/apiError';
import type { Workflow } from '../models/workflow';
import type { ExposureReport, ResilienceReport } from '../models/safety';

export class SafetyApiError extends Error {}

async function post<T>(token: string | undefined, path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/workflows/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    });
  } catch {
    throw new SafetyApiError('Could not reach backend. Is it running on port 8000?');
  }
  const data = await res.json().catch(() => null) as unknown;
  if (!res.ok) throw new SafetyApiError(formatApiError(data, res.status));
  return data as T;
}

export const safetyApi = {
  /** Static analysis; free. */
  exposure: (token: string | undefined, workflow: Workflow) =>
    post<ExposureReport>(token, 'injection-exposure', { workflow }),

  /** Makes each external step fail in turn (mock mode). Counts as one execution. */
  resilience: (token: string | undefined, workflow: Workflow, input: Record<string, unknown>) =>
    post<ResilienceReport>(token, 'resilience', { workflow, input }),
};
