import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { RunHistoryModal } from './RunHistoryModal';
import { formatRunTime } from './runUtils';
import { TracePanel } from './TracePanel';
import { EvaluationPanel } from './EvaluationPanel';
import { Toolbar } from '../../components/Toolbar';
import type { ExecutionTrace, SimulationSettings } from '../../models/simulation';
import type { RunSummary } from '../../models/runs';

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ session: { access_token: 'test-token' } }),
}));

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
beforeEach(() => fetchMock.mockReset());

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });

const run = (over: Partial<RunSummary> = {}): RunSummary => ({
  id: 'r1', workflow_id: 'wf', workflow_name: 'Support Bot', status: 'complete',
  step_count: 5, truncated: false, evaluation_score: null, created_at: new Date().toISOString(), ...over,
});

describe('formatRunTime', () => {
  const now = new Date('2026-11-24T12:00:00Z');
  it('formats relative times', () => {
    expect(formatRunTime('2026-11-24T11:59:40Z', now)).toBe('just now');
    expect(formatRunTime('2026-11-24T11:30:00Z', now)).toBe('30 min ago');
    expect(formatRunTime('2026-11-24T09:00:00Z', now)).toBe('3 h ago');
  });
  it('falls back to the raw text for invalid dates', () => {
    expect(formatRunTime('nonsense', now)).toBe('nonsense');
  });
});

describe('RunHistoryModal', () => {
  it('lists runs, sending the auth token', async () => {
    fetchMock.mockResolvedValue(ok({ runs: [run({ evaluation_score: 8 }), run({ id: 'r2', workflow_name: 'Other', truncated: true })] }));
    render(<RunHistoryModal onReplay={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText('Support Bot')).toBeInTheDocument();
    expect(screen.getByText('Other')).toBeInTheDocument();
    expect(screen.getByText(/score 8\/10/)).toBeInTheDocument();
    expect(screen.getByText(/trimmed/)).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/runs?limit=20&offset=0');
    expect(init.headers.Authorization).toBe('Bearer test-token');
  });

  it('shows an empty state', async () => {
    fetchMock.mockResolvedValue(ok({ runs: [] }));
    render(<RunHistoryModal onReplay={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText(/no saved runs yet/i)).toBeInTheDocument();
  });

  it('shows a readable error when loading fails', async () => {
    fetchMock.mockResolvedValue(ok({ detail: 'Access pending approval.' }, 403));
    render(<RunHistoryModal onReplay={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Access pending approval.');
  });

  it('fetches the full run and replays it, then closes', async () => {
    const detail = { ...run(), settings: {}, input: {}, workflow: { nodes: [], edges: [] }, trace: { steps: [] }, evaluation: null };
    fetchMock.mockResolvedValueOnce(ok({ runs: [run()] })).mockResolvedValueOnce(ok(detail));
    const onReplay = vi.fn();
    const onClose = vi.fn();
    render(<RunHistoryModal onReplay={onReplay} onClose={onClose} />);
    fireEvent.click(await screen.findByText('Replay'));
    await waitFor(() => expect(onReplay).toHaveBeenCalledWith(detail));
    expect(fetchMock.mock.calls[1][0]).toContain('/api/runs/r1');
    expect(onClose).toHaveBeenCalled();
  });

  it('deletes a run and removes it from the list', async () => {
    fetchMock.mockResolvedValueOnce(ok({ runs: [run(), run({ id: 'r2', workflow_name: 'Keep me' })] }))
      .mockResolvedValueOnce({ ok: true, status: 204, json: async () => null });
    render(<RunHistoryModal onReplay={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByLabelText('Delete run of Support Bot'));
    await waitFor(() => expect(screen.queryByText('Support Bot')).toBeNull());
    expect(screen.getByText('Keep me')).toBeInTheDocument();
    expect(fetchMock.mock.calls[1][1].method).toBe('DELETE');
  });

  it('offers "Load more" only when a full page came back, and appends', async () => {
    const page = Array.from({ length: 20 }, (_, i) => run({ id: `r${i}`, workflow_name: `W${i}` }));
    fetchMock.mockResolvedValueOnce(ok({ runs: page })).mockResolvedValueOnce(ok({ runs: [run({ id: 'x', workflow_name: 'Last' })] }));
    render(<RunHistoryModal onReplay={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByText('Load more'));
    expect(await screen.findByText('Last')).toBeInTheDocument();
    expect(fetchMock.mock.calls[1][0]).toContain('offset=20');
    expect(screen.queryByText('Load more')).toBeNull();
  });

  it('closes on Escape', async () => {
    fetchMock.mockResolvedValue(ok({ runs: [] }));
    const onClose = vi.fn();
    render(<RunHistoryModal onReplay={vi.fn()} onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});

describe('TracePanel — branch choice (user-pick)', () => {
  const settings: SimulationSettings = {
    llm_mode: 'mock', hitl_mode: 'auto-approve', condition_mode: 'user-pick',
    display_mode: 'instant', animation_delay_ms: 600, evaluate: false,
  };
  const trace: ExecutionTrace = {
    trace_id: 't', workflow_id: 'w', workflow_name: 'W', started_at: '2026-01-01T00:00:00Z', status: 'paused',
    steps: [
      { node_id: 's', node_name: 'Start', node_type: 'START', status: 'success', started_at: 'x', output: {} },
      { node_id: 'c', node_name: 'Decide', node_type: 'CONDITION', status: 'waiting', started_at: 'x', output: {} },
    ],
    pending_choice: {
      node_id: 'c',
      options: [
        { target_id: 'a', target_name: 'Approve path', label: 'yes' },
        { target_id: 'b', target_name: 'Reject path', label: null },
      ],
    },
  };

  it('shows one button per branch and resumes with the chosen target', () => {
    const onResume = vi.fn();
    render(<TracePanel trace={trace} evaluation={null} settings={settings} visibleStepCount={2}
      onAdvanceStep={vi.fn()} onResume={onResume} onRerun={vi.fn()} onClear={vi.fn()} />);
    expect(screen.getByRole('group', { name: /choose a branch/i })).toBeInTheDocument();
    fireEvent.click(screen.getByText('yes → Approve path'));
    expect(onResume).toHaveBeenCalledWith('c', 'choose', 'a');
    fireEvent.click(screen.getByText('Reject path'));
    expect(onResume).toHaveBeenCalledWith('c', 'choose', 'b');
  });

  it('does not show approve/reject for a condition pause', () => {
    render(<TracePanel trace={trace} evaluation={null} settings={settings} visibleStepCount={2}
      onAdvanceStep={vi.fn()} onResume={vi.fn()} onRerun={vi.fn()} onClear={vi.fn()} />);
    expect(screen.queryByText('Approve')).toBeNull();
    expect(screen.queryByText('Reject')).toBeNull();
  });
});

describe('EvaluationPanel — fallback note', () => {
  const base = { score: 6, summary: 'ok', strengths: [], issues: [], recommendations: [] };
  it('explains when the AI review fell back to mock', () => {
    render(<EvaluationPanel evaluation={{ ...base, source: 'mock', fallback_reason: 'LLM evaluation unavailable (quota)' }} />);
    expect(screen.getByRole('note')).toHaveTextContent(/quota/);
  });
  it('shows nothing extra normally', () => {
    render(<EvaluationPanel evaluation={{ ...base, source: 'llm', fallback_reason: null }} />);
    expect(screen.queryByRole('note')).toBeNull();
  });
});

describe('Toolbar — History', () => {
  const props = {
    workflowName: 'W', onNew: vi.fn(), onSave: vi.fn(), onOpen: vi.fn(), onOpenExamplePicker: vi.fn(),
    onValidate: vi.fn(), onGenerate: vi.fn(), onRefine: vi.fn(), onSimulate: vi.fn(), onEditJson: vi.fn(), onNameChange: vi.fn(),
  };
  it('calls onHistory', () => {
    const onHistory = vi.fn();
    render(<Toolbar {...props} onHistory={onHistory} />);
    fireEvent.click(screen.getByRole('button', { name: 'History' }));
    expect(onHistory).toHaveBeenCalledOnce();
  });
});
