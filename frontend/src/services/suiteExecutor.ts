import { ApiError } from './suites';
import type { CaseResult } from '../models/suites';

export const DEFAULT_CONCURRENCY = 3;

export interface ExecuteOptions {
  caseIds: string[];
  /** Runs one case on the server and returns its result. */
  runCase: (caseId: string) => Promise<CaseResult>;
  onResult: (result: CaseResult) => void;
  signal?: AbortSignal;
  concurrency?: number;
}

export interface ExecuteOutcome {
  completed: number;
  /** Why execution stopped early (limit reached, run cancelled, network down…); undefined when every case ran. */
  stoppedReason?: string;
  cancelled: boolean;
}

/**
 * Client-driven suite executor (design note, Option A): the browser calls "run case" for each case
 * with a small number in flight. The server stores results, so closing the tab only pauses the run.
 * A hard error (429 allowance used up, 409 run closed, network failure) stops everything.
 */
export async function executeSuite(opts: ExecuteOptions): Promise<ExecuteOutcome> {
  const { caseIds, runCase, onResult, signal } = opts;
  const workers = Math.max(1, Math.min(opts.concurrency ?? DEFAULT_CONCURRENCY, caseIds.length || 1));
  let next = 0;
  let completed = 0;
  let stoppedReason: string | undefined;

  const worker = async () => {
    while (!stoppedReason && !signal?.aborted) {
      const index = next++;
      if (index >= caseIds.length) return;
      try {
        onResult(await runCase(caseIds[index]));
        completed++;
      } catch (err) {
        if (!stoppedReason) {
          stoppedReason = err instanceof ApiError || err instanceof Error ? err.message : 'Unexpected error';
        }
      }
    }
  };

  await Promise.all(Array.from({ length: workers }, worker));
  return { completed, stoppedReason, cancelled: !!signal?.aborted };
}
