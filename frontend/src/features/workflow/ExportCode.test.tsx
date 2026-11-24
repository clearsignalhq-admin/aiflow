import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ExportCodeModal } from './ExportCodeModal';
import { exportLangGraph } from '../../services/codeExport';
import * as download from '../../utils/download';
import { NodeType } from '../../models/workflow';
import type { Workflow } from '../../models/workflow';

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ session: { access_token: 'tok' } }),
}));

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
beforeEach(() => { fetchMock.mockReset(); vi.restoreAllMocks(); });

const workflow: Workflow = {
  version: '1.0', id: 'wf-1', name: 'Support Bot', description: '',
  nodes: [{ id: 's', type: NodeType.START, name: 'Start', position: { x: 0, y: 0 }, config: {} }], edges: [], metadata: {},
};

const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });
const zip = (disposition: string | null = 'attachment; filename="support-bot-langgraph.zip"') => ({
  ok: true, status: 200,
  headers: { get: (name: string) => (name.toLowerCase() === 'content-disposition' ? disposition : null) },
  blob: async () => new Blob(['zipdata']),
});

describe('exportLangGraph', () => {
  it('posts the workflow with the token and returns the file with its server-chosen name', async () => {
    fetchMock.mockResolvedValue(zip());
    const out = await exportLangGraph('tok', workflow);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/workflows/export/langgraph');
    expect(init.method).toBe('POST');
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(JSON.parse(init.body)).toEqual({ workflow });
    expect(out.filename).toBe('support-bot-langgraph.zip');
    expect(await out.blob.text()).toBe('zipdata');
  });

  it('includes the suite id only when one is chosen, and falls back to a default name', async () => {
    fetchMock.mockResolvedValue(zip(null));
    const out = await exportLangGraph('tok', workflow, 'suite-1');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ workflow, suite_id: 'suite-1' });
    expect(out.filename).toBe('workflow-langgraph.zip');
  });

  it('turns server errors into readable messages', async () => {
    fetchMock.mockResolvedValue(json({ detail: 'The workflow needs exactly one START node to be exported (it has 0).' }, 422));
    await expect(exportLangGraph('t', workflow)).rejects.toThrow('exactly one START node');
    fetchMock.mockResolvedValue(json({ detail: [{ loc: ['body', 'workflow', 'nodes'], msg: 'List should have at most 100 items' }] }, 422));
    await expect(exportLangGraph('t', workflow)).rejects.toThrow('workflow → nodes: List should have at most 100 items');
  });

  it('explains when the backend cannot be reached', async () => {
    // a plain function: vitest reports a vi.fn()\'s rejected promise as an unhandled error
    vi.stubGlobal('fetch', async () => { throw new TypeError('Failed to fetch'); });
    await expect(exportLangGraph('t', workflow)).rejects.toThrow('Could not reach backend');
    vi.stubGlobal('fetch', fetchMock);
  });
});

describe('ExportCodeModal', () => {
  const suites = [
    { id: 's1', workflow_id: 'wf-1', name: 'Refund cases', case_count: 4, updated_at: 't' },
    { id: 's2', workflow_id: 'wf-1', name: 'Empty suite', case_count: 0, updated_at: 't' },
  ];

  const open = async () => {
    const onClose = vi.fn();
    render(<ExportCodeModal workflow={workflow} onClose={onClose} />);
    await screen.findByText('Refund cases (4 cases)');
    return onClose;
  };

  it('offers only suites that have cases', async () => {
    fetchMock.mockResolvedValueOnce(json({ suites }));
    await open();
    expect(screen.queryByText(/Empty suite/)).toBeNull();
    expect(fetchMock.mock.calls[0][0]).toContain('/api/suites?workflow_id=wf-1');
  });

  it('downloads the project and shows what to do next', async () => {
    fetchMock.mockResolvedValueOnce(json({ suites })).mockResolvedValueOnce(zip());
    const save = vi.spyOn(download, 'downloadBlob').mockImplementation(() => undefined);
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'Download project (.zip)' }));
    expect(await screen.findByRole('status')).toHaveTextContent('support-bot-langgraph.zip downloaded');
    expect(save).toHaveBeenCalledWith(expect.any(Blob), 'support-bot-langgraph.zip');
    expect(screen.getByText(/python main.py --mock/)).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ workflow });     // no suite chosen → no suite id
  });

  it('includes the chosen suite', async () => {
    fetchMock.mockResolvedValueOnce(json({ suites })).mockResolvedValueOnce(zip());
    vi.spyOn(download, 'downloadBlob').mockImplementation(() => undefined);
    await open();
    fireEvent.change(screen.getByLabelText('Generate tests from a test suite'), { target: { value: 's1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Download project (.zip)' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ workflow, suite_id: 's1' });
  });

  it('shows the error and does not claim success', async () => {
    fetchMock.mockResolvedValueOnce(json({ suites })).mockResolvedValueOnce(json({ detail: 'That suite belongs to a different workflow.' }, 422));
    const save = vi.spyOn(download, 'downloadBlob').mockImplementation(() => undefined);
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'Download project (.zip)' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('different workflow');
    expect(save).not.toHaveBeenCalled();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('still works when the suites cannot be loaded', async () => {
    vi.stubGlobal('fetch', async () => ({ ok: false, status: 403, json: async () => ({ detail: 'nope' }) }));
    render(<ExportCodeModal workflow={workflow} onClose={vi.fn()} />);
    expect(await screen.findByRole('button', { name: 'Download project (.zip)' })).toBeEnabled();
    expect(screen.getByLabelText('Generate tests from a test suite')).toHaveValue('');
    vi.stubGlobal('fetch', fetchMock);
  });

  it('closes on Escape', async () => {
    fetchMock.mockResolvedValueOnce(json({ suites: [] }));
    const onClose = vi.fn();
    render(<ExportCodeModal workflow={workflow} onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});
