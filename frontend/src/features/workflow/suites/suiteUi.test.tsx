import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { AssertionEditor } from './AssertionEditor';
import { SuiteReport } from './SuiteReport';
import { SuiteModal } from './SuiteModal';
import { newAssertion } from './assertionUtils';
import { ApiError } from '../../../services/suites';
import { NodeType } from '../../../models/workflow';
import type { Workflow } from '../../../models/workflow';
import type {
  Assertion, CaseResult, RunEstimate, SuiteDetail, SuiteRunDetail,
} from '../../../models/suites';

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock('../../../context/AuthContext', () => ({
  useAuth: () => ({ session: { access_token: 'tok' }, profile: { role: 'user' } }),
}));

// Behaviour of the API is controlled per test through `api`. Functions that may fail are plain
// functions (not vi.fn()) because vitest reports a mock's rejected promise as an unhandled error.
const api = {
  list: vi.fn(),
  get: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  createRun: vi.fn(),
  estimateRun: vi.fn(),
  getRun: vi.fn(),
  cancelRun: vi.fn(),
  listRuns: vi.fn(),
  runCaseLog: [] as string[],
  runCaseImpl: async (_caseId: string): Promise<CaseResult> => { throw new Error('not configured'); },
};

vi.mock('../../../services/suites', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/suites')>();
  return {
    ...actual,
    suiteApi: {
      list: (...a: unknown[]) => api.list(...a),
      get: (...a: unknown[]) => api.get(...a),
      create: (...a: unknown[]) => api.create(...a),
      update: (...a: unknown[]) => api.update(...a),
      remove: (...a: unknown[]) => api.remove(...a),
      createRun: (...a: unknown[]) => api.createRun(...a),
      estimateRun: (...a: unknown[]) => api.estimateRun(...a),
      getRun: (...a: unknown[]) => api.getRun(...a),
      cancelRun: (...a: unknown[]) => api.cancelRun(...a),
      listRuns: (...a: unknown[]) => api.listRuns(...a),
      runCase: async (_token: unknown, _runId: string, caseId: string) => {
        api.runCaseLog.push(caseId);
        return api.runCaseImpl(caseId);
      },
    },
  };
});

// ── Fixtures ─────────────────────────────────────────────────────────────────

const workflow: Workflow = {
  version: '1.0', id: 'wf-1', name: 'W', description: '',
  nodes: [
    { id: 's', type: NodeType.START, name: 'Start', position: { x: 0, y: 0 }, config: {} },
    { id: 'h', type: NodeType.HITL, name: 'Human Review', position: { x: 0, y: 1 }, config: {} },
    { id: 'e', type: NodeType.END, name: 'End', position: { x: 0, y: 2 }, config: {} },
  ],
  edges: [],
  metadata: { sample_input: { message: 'hello' } },
};

const suite = (cases: SuiteDetail['cases'] = [
  { id: 'c1', name: 'First', input: { a: 1 }, assertions: [{ type: 'equals', path: 'a', value: 1 }], tags: [], seed: null },
  { id: 'c2', name: 'Second', input: {}, assertions: [], tags: [], seed: null },
]): SuiteDetail => ({ id: 's1', workflow_id: 'wf-1', name: 'My suite', cases, created_at: 't', updated_at: 't2' });

const result = (id: string, name: string, status: CaseResult['status'] = 'passed', extra: Partial<CaseResult> = {}): CaseResult => ({
  case_id: id, case_name: name, status, duration_ms: 3, assertion_results: [], path: ['s', 'e'], edges_taken: [], warnings: [], ...extra,
});

const report = (over: Partial<SuiteRunDetail['report']> = {}): SuiteRunDetail['report'] => ({
  total: 2, completed: 2, passed: 2, failed: 0, errors: 0, pass_rate: 1,
  coverage: { node_visits: {}, never_visited: [], edges_taken: {}, edges_never_taken: [], node_failures: {} }, ...over,
});

const run = (over: Partial<SuiteRunDetail> = {}): SuiteRunDetail => ({
  id: 'r1', suite_id: 's1', status: 'running', case_count: 2, seed: 0,
  cases: [{ id: 'c1', name: 'First' }, { id: 'c2', name: 'Second' }], results: [], report: report(), created_at: 't', ...over,
});

beforeEach(() => {
  Object.values(api).forEach((v) => { if (typeof v === 'function' && 'mockReset' in v) (v as ReturnType<typeof vi.fn>).mockReset(); });
  api.runCaseLog = [];
  api.runCaseImpl = async (id) => result(id, id);
  api.list.mockResolvedValue([{ id: 's1', workflow_id: 'wf-1', name: 'My suite', case_count: 2, updated_at: 't' }]);
  api.get.mockResolvedValue(suite());
  api.listRuns.mockResolvedValue([]);
  api.cancelRun.mockResolvedValue(run({ status: 'cancelled' }));
});

afterEach(() => vi.restoreAllMocks());

const open = async () => {
  const onClose = vi.fn();
  render(<SuiteModal workflow={workflow} onClose={onClose} />);
  await screen.findByLabelText('Suite name');
  return onClose;
};

// ═══════════════ AssertionEditor ═══════════════

describe('AssertionEditor', () => {
  const nodes = [{ id: 'h', name: 'Human Review' }];
  const setup = (a: Assertion) => {
    const onChange = vi.fn();
    const onRemove = vi.fn();
    render(<AssertionEditor assertion={a} nodes={nodes} onChange={onChange} onRemove={onRemove} />);
    return { onChange, onRemove };
  };

  it('edits an equals check with loose value parsing', () => {
    const { onChange } = setup({ type: 'equals', path: 'a', value: 'x' });
    fireEvent.change(screen.getByLabelText('Expected value'), { target: { value: '42' } });
    expect(onChange).toHaveBeenLastCalledWith({ type: 'equals', path: 'a', value: 42 });
    fireEvent.change(screen.getByLabelText('Output path'), { target: { value: 'b.c' } });
    expect(onChange).toHaveBeenLastCalledWith({ type: 'equals', path: 'b.c', value: 'x' });
  });

  it('shows the fields for each type', () => {
    setup({ type: 'compare', path: 'n', op: '>', value: 3 });
    expect(screen.getByLabelText('Comparison')).toHaveValue('>');
    expect(screen.getByLabelText('Compare with')).toHaveValue(3);
  });

  it('turns comma-separated text into a list for one_of', () => {
    const { onChange } = setup({ type: 'one_of', path: 't', values: [] });
    fireEvent.change(screen.getByLabelText('Allowed values'), { target: { value: 'basic, 5, "7"' } });
    expect(onChange).toHaveBeenLastCalledWith({ type: 'one_of', path: 't', values: ['basic', 5, '7'] });
  });

  it('offers workflow nodes for node checks', () => {
    const { onChange } = setup({ type: 'visits_node', node_id: '' });
    fireEvent.change(screen.getByLabelText('Node'), { target: { value: 'h' } });
    expect(onChange).toHaveBeenLastCalledWith({ type: 'visits_node', node_id: 'h' });
  });

  it('edits schema JSON and ignores invalid JSON', () => {
    const { onChange } = setup({ type: 'matches_schema', path: '', output_schema: { type: 'object' } });
    fireEvent.change(screen.getByLabelText('Output schema'), { target: { value: '{"type":"string"}' } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ output_schema: { type: 'string' } }));
    onChange.mockClear();
    fireEvent.change(screen.getByLabelText('Output schema'), { target: { value: '{oops' } });
    expect(onChange).not.toHaveBeenCalled();
  });

  it('changing the type resets type-specific fields but keeps path and label', () => {
    const { onChange } = setup({ type: 'equals', path: 'a.b', value: 1, label: 'keep me' });
    fireEvent.change(screen.getByLabelText('Assertion type'), { target: { value: 'exists' } });
    expect(onChange).toHaveBeenLastCalledWith({ type: 'exists', path: 'a.b', value: true, label: 'keep me' });
  });

  it('shows what is missing and supports remove, label and the exists checkbox', () => {
    const { onChange, onRemove } = setup({ type: 'exists', path: '', value: true });
    expect(screen.getByRole('alert')).toHaveTextContent(/field path/i);
    fireEvent.click(screen.getByLabelText('Must exist'));
    expect(onChange).toHaveBeenLastCalledWith({ type: 'exists', path: '', value: false });
    fireEvent.change(screen.getByLabelText('Assertion label'), { target: { value: 'my label' } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ label: 'my label' }));
    fireEvent.click(screen.getByLabelText('Remove assertion'));
    expect(onRemove).toHaveBeenCalled();
  });

  it('every type renders without crashing', () => {
    for (const t of ['equals', 'contains', 'exists', 'compare', 'one_of', 'matches_schema', 'expression', 'visits_node', 'skips_node', 'max_steps'] as const) {
      const { unmount } = render(<AssertionEditor assertion={newAssertion(t)} nodes={nodes} onChange={vi.fn()} onRemove={vi.fn()} />);
      expect(screen.getByLabelText('Assertion type')).toHaveValue(t);
      unmount();
    }
  });
});

// ═══════════════ SuiteReport ═══════════════

describe('SuiteReport', () => {
  const names = { s: 'Start', h: 'Human Review', e: 'End', c: 'Route' };

  it('shows live progress without coverage while running', () => {
    render(<SuiteReport nodeNames={names} run={run({ results: [result('c1', 'First')] })} />);
    expect(screen.getByTestId('pass-rate')).toHaveTextContent('100%');
    expect(screen.getByText(/1 pending/)).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '1');
    expect(screen.queryByText('Coverage')).toBeNull();
  });

  it('computes counts from the results themselves', () => {
    render(<SuiteReport nodeNames={names} run={run({ status: 'complete', results: [
      result('c1', 'First'),
      result('c2', 'Second', 'failed', { assertion_results: [{ index: 0, type: 'equals', label: 'tier is gold', passed: false, message: "output.tier is 'basic', expected 'gold'" }] }),
    ] })} />);
    expect(screen.getByTestId('pass-rate')).toHaveTextContent('50%');
    expect(screen.getByText('1 passed')).toBeInTheDocument();
    expect(screen.getByText('1 failed')).toBeInTheDocument();
    // failures are expanded by default and show the reason
    expect(screen.getByText(/expected 'gold'/)).toBeInTheDocument();
  });

  it('shows errors with the failing node name', () => {
    render(<SuiteReport nodeNames={names} run={run({ status: 'complete', results: [
      result('c1', 'First', 'error', { error: 'bad thing', error_node_id: 'h', path: ['s', 'h'] }),
    ] })} />);
    expect(screen.getByText(/Error at Human Review: bad thing/)).toBeInTheDocument();
    expect(screen.getByText(/Path: Start → Human Review/)).toBeInTheDocument();
  });

  it('passing cases are collapsed until clicked', () => {
    render(<SuiteReport nodeNames={names} run={run({ status: 'complete', results: [
      result('c1', 'First', 'passed', { assertion_results: [{ index: 0, type: 'equals', label: 'ok check', passed: true, message: 'fine' }] }),
    ] })} />);
    expect(screen.queryByText(/fine/)).toBeNull();
    fireEvent.click(screen.getByText('First'));
    expect(screen.getByText(/fine/)).toBeInTheDocument();
  });

  it('lists coverage gaps and hotspots by node name once finished', () => {
    render(<SuiteReport nodeNames={names} run={run({
      status: 'complete', results: [result('c1', 'First', 'failed')],
      report: report({ coverage: {
        node_visits: {}, never_visited: ['h'], edges_taken: {},
        edges_never_taken: [{ source: 'c', target: 'h', label: 'premium' }], node_failures: { c: 2, s: 1 },
      } }),
    })} />);
    expect(screen.getByTestId('never-visited')).toHaveTextContent('Never executed: Human Review');
    expect(screen.getByTestId('never-taken')).toHaveTextContent('Route → Human Review (premium)');
    expect(screen.getByTestId('hotspots')).toHaveTextContent('Route (2), Start (1)');
  });

  it('says so when everything was covered, and shows a failure note', () => {
    render(<SuiteReport nodeNames={names} run={run({ status: 'failed', note: 'Stopped: stale', results: [result('c1', 'First')] })} />);
    expect(screen.getByText(/Every node and branch was exercised/)).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent('Stopped: stale');
  });
});

// ═══════════════ SuiteModal ═══════════════

describe('SuiteModal — loading and editing', () => {
  it('opens the first suite and shows its cases', async () => {
    await open();
    expect(api.list).toHaveBeenCalledWith('tok', 'wf-1');
    expect(screen.getByLabelText('Suite name')).toHaveValue('My suite');
    expect(screen.getByLabelText('Case 1 name')).toHaveValue('First');
    expect(screen.getByLabelText('Case 2 name')).toHaveValue('Second');
    expect(screen.getByText('2 / 50 cases')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Saved' })).toBeDisabled();
  });

  it('offers to create the first suite when there are none', async () => {
    api.list.mockResolvedValue([]);
    render(<SuiteModal workflow={workflow} onClose={vi.fn()} />);
    expect(await screen.findByText(/No test suites for this workflow yet/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Suite name')).toBeNull();
  });

  it('creates a suite with a starter case built from the sample input', async () => {
    api.list.mockResolvedValue([]);
    api.create.mockResolvedValue(suite([{ id: 'n1', name: 'Case 1', input: { message: 'hello' }, assertions: [], tags: [], seed: null }]));
    api.get.mockResolvedValue(suite([{ id: 'n1', name: 'Case 1', input: { message: 'hello' }, assertions: [], tags: [], seed: null }]));
    render(<SuiteModal workflow={workflow} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByText('+ New suite'));
    await screen.findByLabelText('Suite name');
    const [, workflowId, name, cases] = api.create.mock.calls[0];
    expect([workflowId, name]).toEqual(['wf-1', 'Suite 1']);
    expect(cases).toEqual([expect.objectContaining({ name: 'Case 1', input: { message: 'hello' } })]);
  });

  it('marks changes as unsaved and saves them', async () => {
    api.update.mockImplementation(async (_t: string, _id: string, name: string, cases: SuiteDetail['cases']) => suite(cases).id && ({ ...suite(cases), name }));
    await open();
    fireEvent.change(screen.getByLabelText('Suite name'), { target: { value: 'Renamed' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Saved' })).toBeDisabled());
    const [token, id, name, cases] = api.update.mock.calls[0];
    expect([token, id, name]).toEqual(['tok', 's1', 'Renamed']);
    expect(cases).toHaveLength(2);
  });

  it('adds and removes cases and assertions', async () => {
    await open();
    fireEvent.click(screen.getByText('+ Add case'));
    expect(screen.getByLabelText('Case 3 name')).toHaveValue('Case 3');
    fireEvent.click(screen.getByLabelText('Remove case 3'));
    expect(screen.queryByLabelText('Case 3 name')).toBeNull();

    const before = screen.getAllByTestId('assertion-row').length;
    fireEvent.click(screen.getByText('+ Add check'));
    expect(screen.getAllByTestId('assertion-row')).toHaveLength(before + 1);
    fireEvent.click(screen.getAllByLabelText('Remove assertion')[0]);
    expect(screen.getAllByTestId('assertion-row')).toHaveLength(before);
  });

  it('adds a case from the sample input', async () => {
    await open();
    fireEvent.click(screen.getByText('+ Add case from sample input'));
    fireEvent.click(screen.getByLabelText('Expand case'));   // first collapsed toggle belongs to the previous cases
    expect(screen.getByLabelText('Case 3 input')).toHaveValue(JSON.stringify({ message: 'hello' }, null, 2));
  });

  it('blocks saving while a check is incomplete and says why', async () => {
    api.get.mockResolvedValue(suite([{ id: 'c1', name: 'First', input: {}, assertions: [{ type: 'exists', path: '' }], tags: [], seed: null }]));
    await open();
    fireEvent.change(screen.getByLabelText('Suite name'), { target: { value: 'x' } });   // make it dirty
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findAllByText(/field path/i)).not.toHaveLength(0);
    expect(api.update).not.toHaveBeenCalled();
  });

  it('asks before discarding unsaved changes on close', async () => {
    const onClose = await open();
    fireEvent.change(screen.getByLabelText('Suite name'), { target: { value: 'changed' } });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    fireEvent.click(screen.getByLabelText('Close'));
    expect(confirm).toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByLabelText('Close'));
    expect(onClose).toHaveBeenCalled();
  });

  it('closes straight away when nothing changed', async () => {
    const onClose = await open();
    const confirm = vi.spyOn(window, 'confirm');
    fireEvent.click(screen.getByLabelText('Close'));
    expect(confirm).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('deletes after confirmation', async () => {
    api.remove.mockResolvedValue(undefined);
    await open();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    api.list.mockResolvedValue([]);
    fireEvent.click(screen.getByText('Delete suite'));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith('tok', 's1'));
    await waitFor(() => expect(screen.queryByLabelText('Suite name')).toBeNull());
  });

  it('shows load errors', async () => {
    api.list.mockImplementation(async () => { throw new ApiError(403, 'Access pending approval.'); });
    render(<SuiteModal workflow={workflow} onClose={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Access pending approval.');
  });
});

describe('SuiteModal — running', () => {
  const finalRun = (over: Partial<SuiteRunDetail> = {}) => run({
    status: 'complete',
    results: [result('c1', 'First'), result('c2', 'Second', 'failed')],
    report: report({ passed: 1, failed: 1, pass_rate: 0.5 }), ...over,
  });

  it('runs every case, then shows the server report', async () => {
    api.createRun.mockResolvedValue(run());
    api.getRun.mockResolvedValue(finalRun());
    api.runCaseImpl = async (id) => (id === 'c2' ? result('c2', 'Second', 'failed') : result('c1', 'First'));
    await open();
    fireEvent.click(screen.getByRole('button', { name: /Run 2 cases/ }));

    await waitFor(() => expect(screen.getByTestId('pass-rate')).toHaveTextContent('50%'));
    expect(api.createRun).toHaveBeenCalledWith('tok', 's1', workflow, 0, 'mock');
    expect([...api.runCaseLog].sort()).toEqual(['c1', 'c2']);
    expect(api.cancelRun).not.toHaveBeenCalled();
    expect(await screen.findByRole('button', { name: /Run 2 cases/ })).toBeEnabled();
  });

  it('saves unsaved edits before running', async () => {
    api.update.mockResolvedValue(suite());
    api.createRun.mockResolvedValue(run());
    api.getRun.mockResolvedValue(finalRun());
    await open();
    fireEvent.change(screen.getByLabelText('Suite name'), { target: { value: 'edited' } });
    fireEvent.click(screen.getByRole('button', { name: /Run 2 cases/ }));
    await waitFor(() => expect(api.createRun).toHaveBeenCalled());
    expect(api.update).toHaveBeenCalled();
    expect(api.update.mock.invocationCallOrder[0]).toBeLessThan(api.createRun.mock.invocationCallOrder[0]);
  });

  it('stops and closes the job when the daily allowance runs out', async () => {
    api.createRun.mockResolvedValue(run());
    api.runCaseImpl = async () => { throw new ApiError(429, 'Daily limit reached'); };
    api.getRun.mockResolvedValue(finalRun({ status: 'cancelled', results: [] }));
    await open();
    fireEvent.click(screen.getByRole('button', { name: /Run 2 cases/ }));
    expect(await screen.findByText(/Stopped early: Daily limit reached/)).toBeInTheDocument();
    expect(api.cancelRun).toHaveBeenCalledWith('tok', 'r1');
  });

  it('shows the error when the run cannot be created', async () => {
    api.createRun.mockImplementation(async () => { throw new ApiError(422, 'The workflow cannot be simulated: cycle'); });
    await open();
    fireEvent.click(screen.getByRole('button', { name: /Run 2 cases/ }));
    expect(await screen.findByText(/cannot be simulated: cycle/)).toBeInTheDocument();
    expect(api.runCaseLog).toEqual([]);
  });

  it('lists previous runs and opens one', async () => {
    api.listRuns.mockResolvedValue([{ id: 'old', suite_id: 's1', status: 'complete', case_count: 4, passed: 3, failed: 1, errors: 0, created_at: '2026-11-24T10:00:00Z' }]);
    api.getRun.mockResolvedValue(finalRun({ id: 'old' }));
    await open();
    const history = await screen.findByText('Previous runs');
    const button = within(history.parentElement as HTMLElement).getByRole('button');
    expect(button).toHaveTextContent('75% passed (3/4)');
    fireEvent.click(button);
    expect(await screen.findByTestId('pass-rate')).toHaveTextContent('50%');
    expect(api.getRun).toHaveBeenCalledWith('tok', 'old');
  });
});


// ═══════════════ Real-model runs ═══════════════

describe('SuiteModal — real model', () => {
  const estimate = (over: Partial<RunEstimate> = {}): RunEstimate => ({
    cases: 2, llm_mode: 'real', llm_calls_per_case_max: 3, llm_calls_max: 6, cost_usd_max: 0.012,
    executions_needed: 2, executions_remaining: null, llm_requests_remaining: 40, allowed: true, reason: null,
    warnings: ["Results can differ between runs because the model's answers vary."], ...over,
  });
  const chooseReal = () => fireEvent.click(screen.getByLabelText(/Real model/));

  it('asks nothing of the server while the run is simulated', async () => {
    await open();
    expect(screen.getByLabelText(/Simulated/)).toBeChecked();
    expect(screen.queryByTestId('estimate')).toBeNull();
    expect(api.estimateRun).not.toHaveBeenCalled();
  });

  it('shows what a real run would use, with the remaining allowance and warnings', async () => {
    api.estimateRun.mockResolvedValue(estimate());
    await open();
    chooseReal();
    const box = await screen.findByTestId('estimate');
    await waitFor(() => expect(box).toHaveTextContent('Up to 6 model calls (3 per case, about $0.012)'));
    expect(api.estimateRun).toHaveBeenCalledWith('tok', 's1', workflow, 'real');
    expect(box).toHaveTextContent('40 AI requests left today');
    expect(box).toHaveTextContent(/answers vary/);
    expect(screen.getByRole('button', { name: /Run 2 cases with the real model/ })).toBeEnabled();
  });

  it('blocks the run and says why when the estimate is not allowed', async () => {
    api.estimateRun.mockResolvedValue(estimate({ allowed: false, reason: 'This run could make up to 6 AI model call(s) but only 2 of your daily 20 remain.' }));
    await open();
    chooseReal();
    expect(await screen.findByRole('alert')).toHaveTextContent('only 2 of your daily 20 remain');
    expect(screen.getByRole('button', { name: /Run 2 cases with the real model/ })).toBeDisabled();
  });

  it('shows an estimate failure as a blocked run instead of crashing', async () => {
    api.estimateRun.mockImplementation(async () => { throw new ApiError(503, 'No AI model is configured on the server.'); });
    await open();
    chooseReal();
    expect(await screen.findByRole('alert')).toHaveTextContent('No AI model is configured');
    expect(screen.getByRole('button', { name: /Run 2 cases with the real model/ })).toBeDisabled();
  });

  it('asks for confirmation (stating the cost) and does nothing if declined', async () => {
    api.estimateRun.mockResolvedValue(estimate());
    await open();
    chooseReal();
    await waitFor(() => expect(screen.getByTestId('estimate')).toHaveTextContent('Up to'));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    fireEvent.click(screen.getByRole('button', { name: /Run 2 cases with the real model/ }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Up to 6 model calls (about $0.012)'));
    expect(api.createRun).not.toHaveBeenCalled();
    expect(api.runCaseLog).toEqual([]);
  });

  it('runs with the real model once confirmed and labels the report', async () => {
    api.estimateRun.mockResolvedValue(estimate());
    api.createRun.mockResolvedValue(run({ llm_mode: 'real' }));
    api.runCaseImpl = async (id) => result(id, id, 'passed', { llm_calls: 3 });
    api.getRun.mockResolvedValue(run({
      status: 'complete', llm_mode: 'real', results: [result('c1', 'First', 'passed', { llm_calls: 3 }), result('c2', 'Second', 'passed', { llm_calls: 3 })],
      report: report({ llm_calls: 6 }),
    }));
    await open();
    chooseReal();
    await waitFor(() => expect(screen.getByTestId('estimate')).toHaveTextContent('Up to'));
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: /Run 2 cases with the real model/ }));

    expect(await screen.findByTestId('real-badge')).toHaveTextContent('real model · 6 calls');
    expect(api.createRun).toHaveBeenCalledWith('tok', 's1', workflow, 0, 'real');
    expect(screen.getAllByText('3 model calls')).toHaveLength(2);
  });

  it('does not show the real-model badge for simulated runs', () => {
    render(<SuiteReport nodeNames={{}} run={run({ status: 'complete', llm_mode: 'mock', results: [result('c1', 'First')] })} />);
    expect(screen.queryByTestId('real-badge')).toBeNull();
    expect(screen.queryByText(/model call/)).toBeNull();
  });

  it('re-estimates when the suite is saved', async () => {
    api.estimateRun.mockResolvedValue(estimate());
    api.update.mockImplementation(async (_t: string, _id: string, name: string, cases: SuiteDetail['cases']) => ({ ...suite(cases), name }));
    await open();
    chooseReal();
    await waitFor(() => expect(screen.getByTestId('estimate')).toHaveTextContent('Up to'));
    expect(api.estimateRun).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('+ Add case'));
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(api.estimateRun).toHaveBeenCalledTimes(2));
  });
});
