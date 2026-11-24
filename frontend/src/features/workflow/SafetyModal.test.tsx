import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SafetyModal } from './SafetyModal';
import { NodeType } from '../../models/workflow';
import type { Workflow } from '../../models/workflow';
import type { ExposureReport, ResilienceReport } from '../../models/safety';

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ session: { access_token: 'tok' }, profile: { role: 'user' } }),
}));

const workflow: Workflow = {
  version: '1.0', id: 'wf', name: 'W', description: '',
  nodes: [{ id: 's', type: NodeType.START, name: 'Start', position: { x: 0, y: 0 }, config: {} }],
  edges: [], metadata: { sample_input: { order: 7 } },
};

const exposure = (over: Partial<ExposureReport> = {}): ExposureReport => ({
  llm_steps: 1, notes: [], exposures: [{
    node_id: 'llm', name: 'Decide', severity: 'high',
    sources: [{ node_id: 'rag', name: 'Policies', kind: 'retrieved documents' }],
    sinks: [{ node_id: 'pay', name: 'Issue refund', action: 'writes through an API', gated: false }],
    message: '“Decide” reads retrieved documents and can lead to “Issue refund”.', advice: 'Put a human review in between.',
  }], ...over,
});

const drillReport = (over: Partial<ResilienceReport> = {}): ResilienceReport => ({
  baseline_status: 'complete', baseline_path: ['s', 'api', 'e'], not_reached: [], skipped: 0, notes: [],
  summary: { handled: 1, ignored: 1, halted: 1, total: 3 },
  results: [
    { node_id: 'api', node_name: 'Fetch', node_type: 'API', kind: 'error', verdict: 'ignored', detail: 'When “Fetch” returns a server error: passed along.', path: [], error: null },
    { node_id: 'api', node_name: 'Fetch', node_type: 'API', kind: 'timeout', verdict: 'halted', detail: 'When “Fetch” times out: stopped.', path: [], error: 'x' },
    { node_id: 'api', node_name: 'Fetch', node_type: 'API', kind: 'empty', verdict: 'handled', detail: 'When “Fetch” returns nothing: reviewed.', path: [], error: null },
  ], ...over,
});

type Call = { path: string; body: Record<string, unknown> };
let calls: Call[];
let responses: Record<string, () => { status: number; body: unknown }>;

beforeEach(() => {
  calls = [];
  responses = { 'injection-exposure': () => ({ status: 200, body: exposure() }) };
  vi.stubGlobal('fetch', async (url: string, init: RequestInit) => {
    const path = String(url).split('/api/workflows/')[1];
    calls.push({ path, body: JSON.parse(String(init.body)) });
    const { status, body } = (responses[path] ?? (() => ({ status: 404, body: null })))();
    return { ok: status < 400, status, json: async () => body } as Response;
  });
});
afterEach(() => vi.unstubAllGlobals());

const open = (onSelectNode?: (id: string) => void) =>
  render(<SafetyModal workflow={workflow} onSelectNode={onSelectNode} onClose={vi.fn()} />);

describe('SafetyModal — exposure', () => {
  it('shows exposed model steps on open, with severity, message and advice', async () => {
    open();
    const card = await screen.findByTestId('exposure');
    expect(card).toHaveTextContent('high');
    expect(card).toHaveTextContent('Decide');
    expect(card).toHaveTextContent('can lead to “Issue refund”');
    expect(card).toHaveTextContent('Put a human review in between.');
    expect(calls[0]).toMatchObject({ path: 'injection-exposure', body: { workflow } });
  });

  it('selects the step when asked to show it', async () => {
    const onSelect = vi.fn();
    open(onSelect);
    fireEvent.click(await screen.findByRole('button', { name: 'Show' }));
    expect(onSelect).toHaveBeenCalledWith('llm');
  });

  it('explains when nothing is exposed', async () => {
    responses['injection-exposure'] = () => ({ status: 200, body: exposure({ exposures: [], notes: ['No LLM step both reads untrusted input and can lead to an action.'] }) });
    open();
    expect(await screen.findByTestId('no-exposure')).toHaveTextContent('No LLM step both reads untrusted input');
  });

  it('shows an error when the analysis fails', async () => {
    responses['injection-exposure'] = () => ({ status: 500, body: null });
    open();
    expect(await screen.findByRole('alert')).toHaveTextContent('Server error (500)');
  });
});

describe('SafetyModal — failure drill', () => {
  it('does not run until asked, then sends the sample input', async () => {
    responses.resilience = () => ({ status: 200, body: drillReport() });
    open();
    await screen.findByTestId('exposure');
    expect(calls.map((c) => c.path)).toEqual(['injection-exposure']);
    expect(screen.queryByTestId('drill')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Run failure drill' }));
    await screen.findByTestId('drill');
    expect(calls[1]).toMatchObject({ path: 'resilience', body: { workflow, input: { order: 7 } } });
  });

  it('reports each failure with its verdict and counts', async () => {
    responses.resilience = () => ({ status: 200, body: drillReport() });
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Run failure drill' }));
    const rows = await screen.findAllByTestId('drill-result');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('Not noticed');
    expect(rows[1]).toHaveTextContent('Stops');
    expect(rows[2]).toHaveTextContent('Handled');
    expect(rows[0]).toHaveTextContent('passed along');
    expect(screen.getByTestId('drill-counts')).toHaveTextContent('1 not noticed · 1 stop the run · 1 handled (of 3)');
  });

  it('shows notes and no counts when the workflow cannot be drilled', async () => {
    responses.resilience = () => ({ status: 200, body: drillReport({ baseline_status: 'error', results: [], notes: ['The workflow does not finish even without a failure. Fix that first.'] }) });
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Run failure drill' }));
    expect(await screen.findByText(/Fix that first/)).toBeInTheDocument();
    expect(screen.queryByTestId('drill-counts')).toBeNull();
  });

  it('shows a limit error', async () => {
    responses.resilience = () => ({ status: 429, body: { detail: 'Daily execution limit (50) reached. Try again tomorrow.' } });
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Run failure drill' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Daily execution limit (50) reached'));
    expect(screen.queryByTestId('drill')).toBeNull();
  });
});
