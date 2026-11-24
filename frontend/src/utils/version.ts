export type VersionRelation = 'match' | 'frontend-older' | 'frontend-newer' | 'unknown';

function parse(v: string): [number, number, number] | null {
  const m = /^(\d+)\.(\d+)\.(\d+)/.exec(v.trim());
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}

/**
 * How this page's version relates to the server's. A different patch number is compatible (bug fixes);
 * a different major or minor number may mean the page and the server disagree about a feature.
 */
export function compareVersions(frontend: string, backend: string | null | undefined): VersionRelation {
  const f = parse(frontend);
  const b = backend ? parse(backend) : null;
  if (!f || !b) return 'unknown';
  for (let i = 0; i < 2; i++) {
    if (f[i] < b[i]) return 'frontend-older';
    if (f[i] > b[i]) return 'frontend-newer';
  }
  return 'match';
}

export interface BackendVersion {
  state: 'loading' | 'ok' | 'unreachable';
  version: string | null;
  commit: string | null;
}

/** One line to paste into a bug report. */
export function versionSummary(frontend: { version: string; commit: string; date: string }, backend: BackendVersion): string {
  const server = backend.state === 'ok' ? `server ${backend.version} (${backend.commit})` : 'server unreachable';
  return `AiFlow ${frontend.version} (page ${frontend.commit}, built ${frontend.date}) · ${server}`;
}
