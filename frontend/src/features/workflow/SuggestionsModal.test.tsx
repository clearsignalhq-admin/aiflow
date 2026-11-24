import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SuggestionsModal } from './SuggestionsModal';
import { NodeType } from '../../models/workflow';
import type { Workflow } from '../../models/workflow';
import type { SuggestedChange } from '../../models/changes';

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ session: { access_token: 'tok' }, profile: { role: 'user' } }),
}));

const workflow: Workflow = {
  version: '1.0', id: 'wf', name: 'W', description: '',
  nodes: [
    { id: 's', type: NodeType.START, name: 'Start', position: { x: 0, y: 0 }, config: {} },
    { id: 'e', type: NodeType.END, name: 'End', position: { x: 0, y: 1 }, config: {} },
  ],
  edges: [], metadata: {},
};

const change = (id: string, title: string, over: Partial<SuggestedChange> = {}): SuggestedChange => ({
  id, title, rationale: `why ${id}`, source: 'lint', ops: [{ op: 'remove_node', id }], summary: [`Do ${id}`], touches: [id], ...over,
});

type Call = { path: string; body: Record<string, unknown> };
let calls: Call[];
let responses: Record<string, () => { status: number; body: unknown }>;

beforeEach(() => {
  calls = [];
  responses = {
    fixes: () => ({ status: 200, body: { changes: [change('a', 'Fix A'), change('b', 'Fix B')] } }),
  };
  vi.stubGlobal('fetch', async (url: string, init: RequestInit) => {
    const path = String(url).split('/api/workflows/')[1];
    calls.push({ path, body: JSON.parse(String(init.body)) });
    const { status, body } = (responses[path] ?? (() => ({ status: 404, body: null })))();
    return { ok: status < 400, status, json: async () => body } as Response;
  });
});
afterEach(() => vi.unstubAllGlobals());

const updated = { ...workflow, name: 'Updated' };
const open = (onApply = vi.fn()) => {
  render(<SuggestionsModal workflow={workflow} onApply={onApply} onClose={vi.fn()} />);
  return onApply;
};

describe('SuggestionsModal — fixes', () => {
  it('lists the fixes for findings with their rationale and plain-language steps', async () => {
    open();
    expect(await screen.findByText('Fix A')).toBeInTheDocument();
    expect(screen.getByText('why a')).toBeInTheDocument();
    expect(screen.getByText('Do b')).toBeInTheDocument();
    expect(calls[0]).toMatchObject({ path: 'fixes', body: { workflow } });
  });

  it('says so when there is nothing to fix', async () => {
    responses.fixes = () => ({ status: 200, body: { changes: [] } });
    open();
    expect(await screen.findByTestId('no-fixes')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Apply all/ })).toBeNull();
  });

  it('applies one fix and hands the edited workflow to the caller', async () => {
    responses['apply-changes'] = () => ({ status: 200, body: { workflow: updated, applied: ['a'], skipped: [], added_node_ids: [] } });
    const onApply = open();
    fireEvent.click(await screen.findByRole('button', { name: 'Apply: Fix A' }));
    await waitFor(() => expect(onApply).toHaveBeenCalledWith(updated, 1));
    expect(calls.find((c) => c.path === 'apply-changes')!.body.changes).toEqual([expect.objectContaining({ id: 'a' })]);
    expect(await screen.findByRole('status')).toHaveTextContent('1 change applied. Undo (Ctrl+Z) reverts them.');
  });

  it('applies all fixes in one request', async () => {
    responses['apply-changes'] = () => ({ status: 200, body: { workflow: updated, applied: ['a', 'b'], skipped: [], added_node_ids: [] } });
    const onApply = open();
    fireEvent.click(await screen.findByRole('button', { name: 'Apply all 2 fixes' }));
    await waitFor(() => expect(onApply).toHaveBeenCalledWith(updated, 2));
    expect((calls.find((c) => c.path === 'apply-changes')!.body.changes as unknown[]).length).toBe(2);
  });

  it('reports changes the server could not apply, and does not edit when none applied', async () => {
    responses['apply-changes'] = () => ({ status: 200, body: { workflow: workflow, applied: [], skipped: [{ id: 'a', reason: 'There is no step with id a.' }], added_node_ids: [] } });
    const onApply = open();
    fireEvent.click(await screen.findByRole('button', { name: 'Apply: Fix A' }));
    expect(await screen.findByRole('status')).toHaveTextContent('0 changes applied');
    expect(screen.getByRole('status')).toHaveTextContent('“Fix A”: There is no step with id a.');
    expect(onApply).not.toHaveBeenCalled();
  });

  it('shows a server error from applying', async () => {
    responses['apply-changes'] = () => ({ status: 422, body: { detail: 'Bad change.' } });
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Apply: Fix A' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Bad change.');
  });

  it('shows an error when fixes cannot be loaded', async () => {
    responses.fixes = () => ({ status: 500, body: null });
    open();
    expect(await screen.findByRole('alert')).toHaveTextContent('Server error (500)');
  });

  it('reloads the fixes when the workflow changes after applying', async () => {
    const { rerender } = render(<SuggestionsModal workflow={workflow} onApply={vi.fn()} onClose={vi.fn()} />);
    await screen.findByText('Fix A');
    responses.fixes = () => ({ status: 200, body: { changes: [change('b', 'Fix B')] } });
    rerender(<SuggestionsModal workflow={updated} onApply={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.queryByText('Fix A')).toBeNull());
    expect(screen.getByText('Fix B')).toBeInTheDocument();
  });
});

describe('SuggestionsModal — describe a change', () => {
  const ask = async (text = 'add a human approval') => {
    await screen.findByText('Fix A');
    fireEvent.change(screen.getByLabelText('Describe the change'), { target: { value: text } });
    fireEvent.click(screen.getByRole('button', { name: 'Suggest changes' }));
  };

  it('needs an instruction before it can ask', async () => {
    open();
    await screen.findByText('Fix A');
    expect(screen.getByRole('button', { name: 'Suggest changes' })).toBeDisabled();
    expect(screen.getByText(/Uses one AI request/)).toBeInTheDocument();
  });

  it('shows the AI proposals and what was discarded', async () => {
    responses.suggest = () => ({ status: 200, body: { summary: 'Add an approval', changes: [change('ai1', 'Add approval', { source: 'ai' })], discarded: ['“Odd” could not be applied: There is no step with id q.'] } });
    open();
    await ask();
    const result = await screen.findByTestId('ai-result');
    expect(result).toHaveTextContent('Add an approval');
    expect(screen.getByText('Add approval')).toBeInTheDocument();
    expect(screen.getByTestId('ai-discarded')).toHaveTextContent('could not be applied');
    expect(calls.find((c) => c.path === 'suggest')!.body).toMatchObject({ instruction: 'add a human approval', workflow });
  });

  it('removes an applied proposal from the list but keeps the others', async () => {
    responses.suggest = () => ({ status: 200, body: { summary: '', changes: [change('p1', 'Proposal 1'), change('p2', 'Proposal 2')], discarded: [] } });
    responses['apply-changes'] = () => ({ status: 200, body: { workflow: updated, applied: ['p1'], skipped: [], added_node_ids: [] } });
    open();
    await ask();
    fireEvent.click(await screen.findByRole('button', { name: 'Apply: Proposal 1' }));
    await waitFor(() => expect(screen.queryByText('Proposal 1')).toBeNull());
    expect(screen.getByText('Proposal 2')).toBeInTheDocument();
  });

  it('says when the AI had nothing usable', async () => {
    responses.suggest = () => ({ status: 200, body: { summary: 'Cannot be done', changes: [], discarded: [] } });
    open();
    await ask();
    expect(await screen.findByText('The AI had no usable changes to suggest.')).toBeInTheDocument();
    expect(screen.getByText('Cannot be done')).toBeInTheDocument();
  });

  it('shows why the request failed (limit, no provider)', async () => {
    responses.suggest = () => ({ status: 429, body: { detail: 'Daily AI request limit (20) reached. Try again tomorrow.' } });
    open();
    await ask();
    expect(await screen.findByRole('alert')).toHaveTextContent('Daily AI request limit (20) reached');
    expect(screen.queryByTestId('ai-result')).toBeNull();
  });
});
