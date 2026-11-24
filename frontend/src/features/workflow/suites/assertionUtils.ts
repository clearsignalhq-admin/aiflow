import type { Assertion, AssertionType, SuiteCase } from '../../../models/suites';

/** Parse what the user typed into a JSON value, falling back to plain text: `5` → 5, `"5"` → "5", `hello` → "hello". */
export function parseLooseValue(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/** Inverse of parseLooseValue: plain strings that are not valid JSON show as typed, everything else as JSON. */
export function formatLooseValue(value: unknown): string {
  if (value === undefined) return '';
  if (typeof value === 'string') {
    try {
      JSON.parse(value);
      return JSON.stringify(value);     // "5" or "true" would otherwise turn into a number/boolean
    } catch {
      return value;
    }
  }
  return JSON.stringify(value);
}

/** One-line description of the options in the UI. */
export const ASSERTION_LABELS: Record<AssertionType, string> = {
  equals: 'Output equals',
  contains: 'Output contains',
  exists: 'Field exists',
  compare: 'Number comparison',
  one_of: 'Output is one of',
  matches_schema: 'Matches schema',
  expression: 'Expression is true',
  visits_node: 'Visits node',
  skips_node: 'Skips node',
  max_steps: 'At most N steps',
};

export function newAssertion(type: AssertionType): Assertion {
  switch (type) {
    case 'equals': return { type, path: '', value: '' };
    case 'contains': return { type, path: '', value: '' };
    case 'exists': return { type, path: '', value: true };
    case 'compare': return { type, path: '', op: '>=', value: 0 };
    case 'one_of': return { type, path: '', values: [] };
    case 'matches_schema': return { type, path: '', output_schema: { type: 'object' } };
    case 'expression': return { type, expression: '' };
    case 'visits_node': return { type, node_id: '' };
    case 'skips_node': return { type, node_id: '' };
    case 'max_steps': return { type, max_steps: 10 };
  }
}

/** Switch type but keep what carries over (label and path). */
export function changeAssertionType(a: Assertion, type: AssertionType): Assertion {
  const fresh = newAssertion(type);
  if (a.label) fresh.label = a.label;
  if ('path' in fresh && a.path !== undefined) fresh.path = a.path;
  return fresh;
}

/** Quick client-side check mirroring the server's rules; null when the assertion is usable. */
export function assertionProblem(a: Assertion): string | null {
  switch (a.type) {
    case 'exists':
      return a.path?.trim() ? null : 'Enter the field path to check.';
    case 'compare':
      if (!a.path?.trim()) return 'Enter the field path to compare.';
      return typeof a.value === 'number' && Number.isFinite(a.value) ? null : 'Enter a number to compare with.';
    case 'one_of':
      return Array.isArray(a.values) && a.values.length > 0 ? null : 'Enter at least one allowed value.';
    case 'matches_schema':
      return a.output_schema && typeof a.output_schema === 'object' ? null : 'Enter a JSON schema.';
    case 'expression':
      return a.expression?.trim() ? null : 'Enter an expression.';
    case 'visits_node':
    case 'skips_node':
      return a.node_id ? null : 'Choose a node.';
    case 'max_steps':
      return Number.isInteger(a.max_steps) && (a.max_steps as number) >= 1 ? null : 'Enter a whole number of at least 1.';
    default:
      return null;
  }
}

export function caseProblem(c: SuiteCase): string | null {
  if (!c.name.trim()) return 'Give the test case a name.';
  for (const a of c.assertions) {
    const problem = assertionProblem(a);
    if (problem) return problem;
  }
  return null;
}

export function blankCase(number: number, sampleInput?: Record<string, unknown>): SuiteCase {
  return { name: `Case ${number}`, input: sampleInput ? { ...sampleInput } : {}, assertions: [], tags: [], seed: null };
}
