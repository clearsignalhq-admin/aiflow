import type { SuiteCase } from '../../../models/suites';

/** A case being edited. `key` is client-only so list items keep their state when others are removed. */
export interface DraftCase {
  key: string;
  data: SuiteCase;
}

let keyCounter = 0;
export const newKey = () => `draft-${++keyCounter}`;

export function toDraft(cases: SuiteCase[]): DraftCase[] {
  return cases.map((data) => ({ key: newKey(), data }));
}

export function fromDraft(draft: DraftCase[]): SuiteCase[] {
  return draft.map((d) => d.data);
}

/** Stable text form used to detect unsaved changes. */
export function serializeSuite(name: string, draft: DraftCase[]): string {
  return JSON.stringify({ name, cases: fromDraft(draft) });
}
