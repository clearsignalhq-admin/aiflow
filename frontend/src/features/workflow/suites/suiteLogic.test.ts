import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  assertionProblem, blankCase, caseProblem, changeAssertionType, formatLooseValue, newAssertion, parseLooseValue,
} from './assertionUtils';
import { fromDraft, newKey, serializeSuite, toDraft } from './draftUtils';
import { percent } from './format';
import { ASSERTION_TYPES } from '../../../models/suites';
import type { Assertion, CaseResult } from '../../../models/suites';
import { executeSuite } from '../../../services/suiteExecutor';
import { ApiError, suiteApi } from '../../../services/suites';

describe('loose values', () => {
  it.each([
    ['5', 5], ['true', true], ['null', null], ['"5"', '5'], ['hello', 'hello'], ['[1,2]', [1, 2]], ['{"a":1}', { a: 1 }],
  ])('parses %s', (text, expected) => {
    expect(parseLooseValue(text)).toEqual(expected);
  });

  it.each([5, true, null, '5', 'true', 'hello', 'two words', [1, 'a'], { a: 1 }])('round-trips %j', (value) => {
    expect(parseLooseValue(formatLooseValue(value))).toEqual(value);
  });

  it('shows plain strings without quotes and ambiguous ones with', () => {
    expect(formatLooseValue('hello')).toBe('hello');
    expect(formatLooseValue('5')).toBe('"5"');
    expect(formatLooseValue(undefined)).toBe('');
  });
});

describe('assertion helpers', () => {
  it('creates a usable default for every type, except where the user must choose', () => {
    for (const type of ASSERTION_TYPES) {
      const a = newAssertion(type);
      expect(a.type).toBe(type);
      const problem = assertionProblem(a);
      if (['exists', 'compare', 'one_of', 'expression', 'visits_node', 'skips_node'].includes(type)) expect(problem).toBeTruthy();
      else expect(problem).toBeNull();
    }
  });

  it('reports what is missing', () => {
    expect(assertionProblem({ type: 'exists', path: '  ' })).toMatch(/path/);
    expect(assertionProblem({ type: 'compare', path: 'a', op: '>', value: undefined })).toMatch(/number/);
    expect(assertionProblem({ type: 'compare', path: 'a', op: '>', value: 3 })).toBeNull();
    expect(assertionProblem({ type: 'one_of', values: [] })).toMatch(/value/);
    expect(assertionProblem({ type: 'expression', expression: '' })).toMatch(/expression/);
    expect(assertionProblem({ type: 'visits_node', node_id: '' })).toMatch(/node/);
    expect(assertionProblem({ type: 'max_steps', max_steps: 0 })).toMatch(/at least 1/);
    expect(assertionProblem({ type: 'max_steps', max_steps: 2.5 })).toMatch(/whole number/);
    expect(assertionProblem({ type: 'equals', value: '' })).toBeNull();
  });

  it('keeps label and path when the type changes', () => {
    const a: Assertion = { type: 'equals', path: 'x.y', value: 1, label: 'my check' };
    expect(changeAssertionType(a, 'compare')).toMatchObject({ type: 'compare', path: 'x.y', label: 'my check', op: '>=' });
    expect(changeAssertionType(a, 'visits_node')).toEqual({ type: 'visits_node', node_id: '', label: 'my check' });
  });

  it('validates cases', () => {
    expect(caseProblem({ ...blankCase(1), name: ' ' })).toMatch(/name/);
    expect(caseProblem({ ...blankCase(1), assertions: [{ type: 'exists', path: '' }] })).toMatch(/path/);
    expect(caseProblem(blankCase(1))).toBeNull();
  });

  it('copies the sample input into a new case', () => {
    const sample = { q: 'hi' };
    const c = blankCase(3, sample);
    expect(c).toMatchObject({ name: 'Case 3', input: { q: 'hi' } });
    c.input.q = 'changed';
    expect(sample.q).toBe('hi');
  });
});

describe('drafts', () => {
  it('assigns unique client keys and round-trips cases', () => {
    const cases = [blankCase(1), blankCase(2)];
    const draft = toDraft(cases);
    expect(new Set(draft.map((d) => d.key)).size).toBe(2);
    expect(newKey()).not.toBe(draft[0].key);
    expect(fromDraft(draft)).toEqual(cases);
  });

  it('detects changes through the serialised form, ignoring keys', () => {
    const a = toDraft([blankCase(1)]);
    const b = toDraft([blankCase(1)]);
    expect(serializeSuite('s', a)).toBe(serializeSuite('s', b));
    b[0].data.name = 'x';
    expect(serializeSuite('s', a)).not.toBe(serializeSuite('s', b));
    expect(serializeSuite('s', a)).not.toBe(serializeSuite('t', a));
  });

  it('formats percentages', () => {
    expect(percent(null)).toBe('—');
    expect(percent(0.5)).toBe('50%');
    expect(percent(1 / 3)).toBe('33%');
  });
});

// ── Executor ─────────────────────────────────────────────────────────────────

const result = (id: string, status: CaseResult['status'] = 'passed'): CaseResult => ({
  case_id: id, case_name: id, status, duration_ms: 1, assertion_results: [], path: [], edges_taken: [], warnings: [],
});

describe('executeSuite', () => {
  it('runs every case and reports each result', async () => {
    const seen: string[] = [];
    const out = await executeSuite({ caseIds: ['a', 'b', 'c'], runCase: async (id) => result(id), onResult: (r) => seen.push(r.case_id) });
    expect(out).toEqual({ completed: 3, stoppedReason: undefined, cancelled: false });
    expect(seen.sort()).toEqual(['a', 'b', 'c']);
  });

  it('never has more than the concurrency limit in flight, and uses all of it', async () => {
    let inFlight = 0;
    let peak = 0;
    await executeSuite({
      caseIds: Array.from({ length: 10 }, (_, i) => `c${i}`),
      concurrency: 3,
      onResult: () => undefined,
      runCase: async (id) => {
        inFlight++;
        peak = Math.max(peak, inFlight);
        await new Promise((r) => setTimeout(r, 5));
        inFlight--;
        return result(id);
      },
    });
    expect(peak).toBe(3);
  });

  it('defaults to three at a time and handles an empty list', async () => {
    let peak = 0;
    let inFlight = 0;
    await executeSuite({
      caseIds: ['1', '2', '3', '4', '5', '6'], onResult: () => undefined,
      runCase: async (id) => { inFlight++; peak = Math.max(peak, inFlight); await new Promise((r) => setTimeout(r, 3)); inFlight--; return result(id); },
    });
    expect(peak).toBe(3);
    expect((await executeSuite({ caseIds: [], runCase: async (id) => result(id), onResult: () => undefined })).completed).toBe(0);
  });

  it('stops launching new cases on a hard error and reports why', async () => {
    const started: string[] = [];
    const out = await executeSuite({
      caseIds: ['a', 'b', 'c', 'd', 'e', 'f'], concurrency: 1, onResult: () => undefined,
      runCase: async (id) => {
        started.push(id);
        if (id === 'c') throw new ApiError(429, 'Daily limit reached');
        return result(id);
      },
    });
    expect(out.stoppedReason).toBe('Daily limit reached');
    expect(out.completed).toBe(2);
    expect(started).toEqual(['a', 'b', 'c']);
  });

  it('stops when aborted and says so', async () => {
    const controller = new AbortController();
    const started: string[] = [];
    const out = await executeSuite({
      caseIds: ['a', 'b', 'c', 'd'], concurrency: 1, signal: controller.signal, onResult: () => undefined,
      runCase: async (id) => { started.push(id); if (id === 'b') controller.abort(); return result(id); },
    });
    expect(out.cancelled).toBe(true);
    expect(started).toEqual(['a', 'b']);
  });
});

// ── API client ───────────────────────────────────────────────────────────────

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
beforeEach(() => fetchMock.mockReset());
const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });

describe('suiteApi', () => {
  it('sends the token and uses the right verbs and URLs', async () => {
    fetchMock.mockResolvedValue(ok({ suites: [] }));
    await suiteApi.list('tok', 'wf 1');
    expect(fetchMock.mock.calls[0][0]).toContain('/api/suites?workflow_id=wf%201');
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer tok');

    fetchMock.mockResolvedValue(ok({ id: 's1' }));
    await suiteApi.create('tok', 'wf', 'n', []);
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'POST' });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ name: 'n', workflow_id: 'wf', cases: [] });

    await suiteApi.update('tok', 's1', 'n2', []);
    expect(fetchMock.mock.calls[2][0]).toContain('/api/suites/s1');
    expect(fetchMock.mock.calls[2][1].method).toBe('PUT');

    await suiteApi.runCase('tok', 'r1', 'c1');
    expect(fetchMock.mock.calls[3][0]).toContain('/api/suite-runs/r1/cases/c1/run');
  });

  it('returns nothing for 204 and maps errors to ApiError with a readable message', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 204, json: async () => { throw new Error('no body'); } });
    await expect(suiteApi.remove('t', 's')).resolves.toBeUndefined();

    fetchMock.mockResolvedValue(ok({ detail: 'Suite not found.' }, 404));
    await expect(suiteApi.get('t', 's')).rejects.toMatchObject({ name: 'ApiError', status: 404, message: 'Suite not found.' });

    fetchMock.mockResolvedValue(ok({ detail: [{ loc: ['body', 'cases', 0, 'name'], msg: 'String should have at least 1 character' }] }, 422));
    await expect(suiteApi.update('t', 's', '', [])).rejects.toThrow(/cases → 0 → name/);

    // A plain function, not a vi.fn(): vitest's call tracking reports a mock's rejected promise as an unhandled error.
    vi.stubGlobal('fetch', async () => { throw new TypeError('Failed to fetch'); });
    const err = await suiteApi.list('t', 'w').catch((e: unknown) => e);
    vi.stubGlobal('fetch', fetchMock);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(0);
    expect((err as ApiError).message).toContain('Could not reach backend');
  });
});
