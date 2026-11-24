import { describe, it, expect } from 'vitest';
import { lintBadges, formatDuration, formatCost, summariseEstimates } from './lintUtils';
import type { LintFinding } from '../../models/lint';

const f = (over: Partial<LintFinding>): LintFinding => ({
  rule_id: 'r', severity: 'warning', node_id: 'a', message: 'm', fix_hint: '', ...over,
});

describe('lintBadges', () => {
  it('groups by node, counts, and takes the worst severity', () => {
    const badges = lintBadges([
      f({ node_id: 'a', severity: 'info', message: 'one' }),
      f({ node_id: 'a', severity: 'error', message: 'two' }),
      f({ node_id: 'b', severity: 'warning', message: 'three' }),
    ]);
    expect(badges.a).toEqual({ severity: 'error', count: 2, title: 'one\ntwo' });
    expect(badges.b.severity).toBe('warning');
  });

  it('ignores findings without a node', () => {
    expect(lintBadges([f({ node_id: null })])).toEqual({});
  });
});

describe('formatting', () => {
  it('formats durations', () => {
    expect(formatDuration(5)).toBe('5 ms');
    expect(formatDuration(2000)).toBe('2 s');
    expect(formatDuration(2500)).toBe('2.5 s');
    expect(formatDuration(300_000)).toBe('5 min');
  });

  it('formats costs', () => {
    expect(formatCost(0)).toBe('$0');
    expect(formatCost(0.002)).toBe('$0.0020');
    expect(formatCost(1.5)).toBe('$1.50');
  });
});

describe('summariseEstimates', () => {
  it('returns null for no paths', () => {
    expect(summariseEstimates([])).toBeNull();
  });

  it('shows ranges across paths and singular/plural', () => {
    const one = summariseEstimates([{ node_ids: [], node_names: [], latency_ms: 2000, cost_usd: 0.002 }]);
    expect(one).toContain('1 path ·');
    const two = summariseEstimates([
      { node_ids: [], node_names: [], latency_ms: 2000, cost_usd: 0.002 },
      { node_ids: [], node_names: [], latency_ms: 4000, cost_usd: 0.004 },
    ]);
    expect(two).toContain('2 paths');
    expect(two).toContain('2 s – 4 s');
    expect(two).toContain('rough estimate');
  });
});
