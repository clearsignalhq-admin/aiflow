const KEY = 'aiflow:recent-actions';
export const MAX_RECENT = 5;

/** Ids of the actions used most recently, newest first. Never throws: storage can be blocked or hold junk. */
export function readRecent(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? '[]') as unknown;
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string').slice(0, MAX_RECENT) : [];
  } catch {
    return [];
  }
}

/** Puts `id` first, without duplicates, and returns the new list. */
export function pushRecent(current: string[], id: string): string[] {
  const next = [id, ...current.filter((x) => x !== id)].slice(0, MAX_RECENT);
  try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* the list just will not persist */ }
  return next;
}
