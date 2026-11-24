import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { RunComparison } from './RunComparison';
import { SuiteModal } from './SuiteModal';
import { ApiError } from '../../../services/suites';
import { NodeType } from '../../../models/workflow';
import type { Workflow } from '../../../models/workflow';
import type { CaseComparison, RunComparison as Comparison, RunSide, SuiteRunDetail, SuiteDetail } from '../../../models/suites';

vi.mock('../../../context/AuthContext', () => ({
  useAuth: () => ({ session: { access_token: 'tok' }, profile: { role: 'user' } }),
}));

const api = {
  list: vi.fn(), get: vi.fn(), listRuns: vi.fn(), getRun: vi.fn(), compareRuns: vi.fn(),
};
vi.mock('../../../services/suites', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/suites')>();
  return {
    ...actual,
    suiteApi: {
      list: (...a: unknown[]) => api.list(...a),
      get: (...a: unknown[]) => api.get(...a),
      listRuns: (...a: unknown[]) => api.listRuns(...a),
      getRun: (...a: unknown[]) => api.getRun(...a),
      compareRuns: (...a: unknown[]) => api.compareRuns(...a),
      estimateRun: vi.fn(),
    },
  };
});

const side = (over: Partial<RunSide> = {}): RunSide => ({
  id: 'x', created_at: '2026-11-24T10:00:00Z', status: 'complete', llm_mode: 'mock', seed: 0, case_count: 4, completed: 4,
  passed: 3, failed: 1, errors: 0, pass_rate: 0.75, llm_calls: 0, total_duration_ms: 20, ...over,
});

const caseCmp = (over: Partial<CaseComparison> = {}): CaseComparison => ({
  case_id: 'c1', case_name: 'Refund over limit', change: 'regressed', base_status: 'passed', head_status: 'failed',
  definition_changed: false, path_changed: false, nodes_added: [], nodes_removed: [], output_changed: false,
  assertion_changes: [], duration_delta_ms: null, llm_calls_delta: null, ...over,
});

const cmp = (over: Partial<Comparison> = {}): Comparison => ({
  base: side({ id: 'base' }), head: side({ id: 'head', created_at: '2026-11-25T10:00:00Z', passed: 2, failed: 2, pass_rate: 0.5 }),
  verdict: 'regression',
  summary: { regressed: 1, fixed: 0, still_failing: 1, unchanged: 2, added: 0, removed: 0, incomplete: 0, pass_rate_delta: -0.25 },
  cases: [caseCmp()], workflow: { nodes: [], edges: [], changed: false },
  coverage: { nodes_newly_visited: [], nodes_no_longer_visited: [], edges_newly_taken: [], edges_no_longer_taken: [] },
  warnings: [], ...over,
});

const names = { fast: 'Fast path', slow: 'Slow path', c: 'Route' };

describe('RunComparison', () => {
  it('leads with the verdict and the pass-rate movement', () => {
    render(<RunComparison comparison={cmp()} nodeNames={names} />);
    const verdict = screen.getByTestId('cmp-verdict');
    expect(verdict).toHaveTextContent('Regression');
    expect(verdict).toHaveTextContent('75% → 50% passed (-25 points)');
    expect(screen.getByTestId('cmp-counts')).toHaveTextContent('1 regressed · 0 fixed · 1 still failing · 2 unchanged');
  });

  it('describes improvements and no-change runs', () => {
    const { rerender } = render(<RunComparison comparison={cmp({ verdict: 'improvement', summary: { ...cmp().summary, regressed: 0, fixed: 2, pass_rate_delta: 0.5 }, cases: [caseCmp({ change: 'fixed', base_status: 'failed', head_status: 'passed' })] })} nodeNames={names} />);
    expect(screen.getByTestId('cmp-verdict')).toHaveTextContent('Improvement');
    expect(screen.getByTestId('cmp-verdict')).toHaveTextContent('+50 points');
    rerender(<RunComparison comparison={cmp({ verdict: 'no_change', cases: [], summary: { ...cmp().summary, regressed: 0, pass_rate_delta: 0 } })} nodeNames={names} />);
    expect(screen.getByTestId('cmp-verdict')).toHaveTextContent('No change');
    expect(screen.getByText('Every case came out the same in both runs.')).toBeInTheDocument();
  });

  it('shows why a regressed case regressed, with step names', () => {
    render(<RunComparison nodeNames={names} comparison={cmp({ cases: [caseCmp({
      assertion_changes: [{ label: 'visits slow path', type: 'visits_node', base_passed: true, head_passed: false, base_message: 'ok', head_message: "node 'slow' was not executed" }],
      path_changed: true, nodes_added: ['fast'], nodes_removed: ['slow'], output_changed: true, head_error: null,
      duration_delta_ms: 12, llm_calls_delta: 2,
    })] })} />);
    const row = screen.getByTestId('cmp-case');
    expect(row).toHaveTextContent('Regressed');
    expect(row).toHaveTextContent('passed → failed');
    expect(row).toHaveTextContent('visits slow path: passed → failed — node \'slow\' was not executed');
    expect(row).toHaveTextContent('now runs: Fast path');
    expect(row).toHaveTextContent('no longer runs: Slow path');
    expect(row).toHaveTextContent('The output changed.');
    expect(row).toHaveTextContent('+12 ms · +2 model calls');
  });

  it('collapses unchanged cases behind a toggle and expands regressions by default', () => {
    render(<RunComparison nodeNames={names} comparison={cmp({ cases: [
      caseCmp({ case_id: 'a', case_name: 'Regressed one', assertion_changes: [{ label: 'chk', type: 'equals', base_passed: true, head_passed: false }] }),
      caseCmp({ case_id: 'b', case_name: 'Still fine', change: 'unchanged', base_status: 'passed', head_status: 'passed' }),
      caseCmp({ case_id: 'c', case_name: 'Also fine', change: 'unchanged', base_status: 'passed', head_status: 'passed' }),
    ] })} />);
    expect(screen.getByText('Regressed one')).toBeInTheDocument();
    expect(screen.getByText('chk')).toBeInTheDocument();                                   // detail is open for a regression
    expect(screen.queryByText('Still fine')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Show 2 unchanged cases' }));
    expect(screen.getByText('Still fine')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Hide 2 unchanged cases' }));
    expect(screen.queryByText('Still fine')).toBeNull();
  });

  it('notes edited test cases and cases that failed with an error', () => {
    render(<RunComparison nodeNames={names} comparison={cmp({ cases: [caseCmp({ definition_changed: true, head_error: 'Timed out after 25s' })] })} />);
    expect(screen.getByText('This test case was edited between the runs.')).toBeInTheDocument();
    expect(screen.getByText('Now: Timed out after 25s')).toBeInTheDocument();
  });

  it('shows the workflow changes that could explain it', () => {
    render(<RunComparison nodeNames={names} comparison={cmp({ workflow: { changed: true,
      nodes: [
        { node_id: 'c', name: 'Route', change: 'modified', fields: [{ field: 'config.expression', before: 'input.mode', after: "'fast'" }] },
        { node_id: 'n', name: 'Audit', change: 'added', fields: [] },
        { node_id: 'o', name: 'Old step', change: 'removed', fields: [] },
      ],
      edges: [{ source: 'c', target: 'n', source_name: 'Route', target_name: 'Audit', label: 'always', change: 'added' }],
    } })} />);
    const box = screen.getByTestId('cmp-workflow');
    expect(box).toHaveTextContent('Edited step “Route”');
    expect(within(box).getByText('config.expression')).toBeInTheDocument();
    expect(box).toHaveTextContent("input.mode → 'fast'");
    expect(box).toHaveTextContent('Added step “Audit”');
    expect(box).toHaveTextContent('Removed step “Old step”');
    expect(box).toHaveTextContent('Added connection Route → Audit (always)');
  });

  it('says when the workflow did not change, and lists coverage movement and warnings', () => {
    render(<RunComparison nodeNames={names} comparison={cmp({
      coverage: { nodes_newly_visited: ['fast'], nodes_no_longer_visited: ['slow'], edges_newly_taken: [], edges_no_longer_taken: [] },
      warnings: ['The runs used different seeds (0 and 5), so the simulated data differs.'],
    })} />);
    expect(screen.getByTestId('cmp-workflow')).toHaveTextContent('identical in both runs');
    expect(screen.getByTestId('cmp-coverage')).toHaveTextContent('No case reaches any more: Slow path. Newly reached: Fast path.');
    expect(screen.getByTestId('cmp-warnings')).toHaveTextContent('different seeds');
  });

  it('labels real-model runs', () => {
    render(<RunComparison nodeNames={names} comparison={cmp({ head: side({ llm_mode: 'real', llm_calls: 7 }) })} />);
    expect(screen.getByText(/real model, 7 calls/)).toBeInTheDocument();
  });
});

// ═══════════════ In the suite dialog ═══════════════

const workflow: Workflow = {
  version: '1.0', id: 'wf-1', name: 'W', description: '',
  nodes: [{ id: 's', type: NodeType.START, name: 'Start', position: { x: 0, y: 0 }, config: {} }, { id: 'c', type: NodeType.CONDITION, name: 'Route', position: { x: 0, y: 1 }, config: {} }],
  edges: [], metadata: {},
};
const suite: SuiteDetail = { id: 's1', workflow_id: 'wf-1', name: 'My suite', created_at: 't', updated_at: 't', cases: [{ id: 'c1', name: 'First', input: {}, assertions: [], tags: [], seed: null }] };
const summary = (id: string, created: string, passed: number) => ({ id, suite_id: 's1', status: 'complete' as const, case_count: 2, passed, failed: 2 - passed, errors: 0, created_at: created });
const detail = (id: string, created: string): SuiteRunDetail => ({
  id, suite_id: 's1', status: 'complete', case_count: 2, seed: 0, cases: [{ id: 'c1', name: 'First' }], results: [],
  report: { total: 2, completed: 0, passed: 0, failed: 0, errors: 0, pass_rate: null, coverage: { node_visits: {}, never_visited: [], edges_taken: {}, edges_never_taken: [], node_failures: {} } },
  created_at: created,
});

describe('SuiteModal — compare', () => {
  beforeEach(() => {
    Object.values(api).forEach((m) => m.mockReset());
    api.list.mockResolvedValue([{ id: 's1', workflow_id: 'wf-1', name: 'My suite', case_count: 1, updated_at: 't' }]);
    api.get.mockResolvedValue(suite);
    api.listRuns.mockResolvedValue([summary('r3', '2026-11-26T10:00:00Z', 2), summary('r2', '2026-11-25T10:00:00Z', 1), summary('r1', '2026-11-24T10:00:00Z', 2)]);
    api.getRun.mockImplementation(async (_t: string, id: string) => detail(id, { r3: '2026-11-26T10:00:00Z', r2: '2026-11-25T10:00:00Z', r1: '2026-11-24T10:00:00Z' }[id]!));
  });

  const open = async () => {
    render(<SuiteModal workflow={workflow} onClose={vi.fn()} />);
    await screen.findByLabelText('Suite name');
    const history = await screen.findByText('Previous runs');
    return within(history.parentElement as HTMLElement).getAllByRole('button');
  };

  it('offers no comparison until a run is on screen', async () => {
    await open();
    expect(screen.queryByLabelText('Compare with')).toBeNull();
  });

  it('defaults to the run just before the one shown and asks the server for the comparison', async () => {
    const buttons = await open();
    fireEvent.click(buttons[1]);                                        // the middle run, r2
    const select = await screen.findByLabelText('Compare with') as HTMLSelectElement;
    expect(select.value).toBe('r1');                                    // older than r2, not the newer r3
    expect(select.options).toHaveLength(2);                             // every run except the one shown

    api.compareRuns.mockResolvedValue(cmp());
    fireEvent.click(screen.getByRole('button', { name: 'Compare' }));
    expect(await screen.findByTestId('cmp-verdict')).toHaveTextContent('Regression');
    expect(api.compareRuns).toHaveBeenCalledWith('tok', 'r1', 'r2');     // (base = earlier, head = shown)
  });

  it('for the oldest run falls back to the nearest other run, and the choice can be changed', async () => {
    const buttons = await open();
    fireEvent.click(buttons[2]);                                        // r1, the oldest
    const select = await screen.findByLabelText('Compare with') as HTMLSelectElement;
    expect(select.value).toBe('r3');
    fireEvent.change(select, { target: { value: 'r2' } });
    api.compareRuns.mockResolvedValue(cmp());
    fireEvent.click(screen.getByRole('button', { name: 'Compare' }));
    await screen.findByTestId('cmp-verdict');
    expect(api.compareRuns).toHaveBeenCalledWith('tok', 'r2', 'r1');
  });

  it('clears the comparison when another run is opened or the base changes', async () => {
    const buttons = await open();
    fireEvent.click(buttons[0]);
    api.compareRuns.mockResolvedValue(cmp());
    fireEvent.click(await screen.findByRole('button', { name: 'Compare' }));
    await screen.findByTestId('cmp-verdict');
    fireEvent.change(screen.getByLabelText('Compare with'), { target: { value: 'r1' } });
    expect(screen.queryByTestId('cmp-verdict')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Compare' }));
    await screen.findByTestId('cmp-verdict');
    fireEvent.click(buttons[1]);
    await screen.findByLabelText('Compare with');
    expect(screen.queryByTestId('cmp-verdict')).toBeNull();
  });

  it('shows the reason when the server refuses', async () => {
    const buttons = await open();
    fireEvent.click(buttons[0]);
    api.compareRuns.mockImplementation(async () => { throw new ApiError(422, 'These runs belong to different suites, so their test cases cannot be compared.'); });
    fireEvent.click(await screen.findByRole('button', { name: 'Compare' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('different suites');
    expect(screen.queryByTestId('cmp-verdict')).toBeNull();
  });

  it('has nothing to compare against when the suite has only one run', async () => {
    api.listRuns.mockResolvedValue([summary('r1', '2026-11-24T10:00:00Z', 2)]);
    const buttons = await open();
    fireEvent.click(buttons[0]);
    await screen.findByTestId('pass-rate');
    expect(screen.queryByLabelText('Compare with')).toBeNull();
  });
});
