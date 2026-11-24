import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ExportCodeModal } from './ExportCodeModal';
import { exportProject } from '../../services/codeExport';
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

describe('exportProject', () => {
  it('posts the workflow with the token and returns the file with its server-chosen name', async () => {
    fetchMock.mockResolvedValue(zip());
    const out = await exportProject('tok', workflow);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/workflows\/export$/);
    expect(init.method).toBe('POST');
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(JSON.parse(init.body)).toEqual({ workflow, target: 'langgraph' });
    expect(out.filename).toBe('support-bot-langgraph.zip');
    expect(await out.blob.text()).toBe('zipdata');
  });

  it('includes the suite id only when one is chosen, and falls back to a default name', async () => {
    fetchMock.mockResolvedValue(zip(null));
    const out = await exportProject('tok', workflow, 'langgraph', 'suite-1');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ workflow, target: 'langgraph', suite_id: 'suite-1' });
    expect(out.filename).toBe('workflow-langgraph.zip');
  });

  it('turns server errors into readable messages', async () => {
    fetchMock.mockResolvedValue(json({ detail: 'The workflow needs exactly one START node to be exported (it has 0).' }, 422));
    await expect(exportProject('t', workflow)).rejects.toThrow('exactly one START node');
    fetchMock.mockResolvedValue(json({ detail: [{ loc: ['body', 'workflow', 'nodes'], msg: 'List should have at most 100 items' }] }, 422));
    await expect(exportProject('t', workflow)).rejects.toThrow('workflow → nodes: List should have at most 100 items');
  });

  it('explains when the backend cannot be reached', async () => {
    // a plain function: vitest reports a vi.fn()\'s rejected promise as an unhandled error
    vi.stubGlobal('fetch', async () => { throw new TypeError('Failed to fetch'); });
    await expect(exportProject('t', workflow)).rejects.toThrow('Could not reach backend');
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
    expect(screen.queryByText(/server.py/)).toBeNull();
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ workflow, target: 'langgraph' });     // no suite chosen → no suite id
  });

  it('includes the chosen suite', async () => {
    fetchMock.mockResolvedValueOnce(json({ suites })).mockResolvedValueOnce(zip());
    vi.spyOn(download, 'downloadBlob').mockImplementation(() => undefined);
    await open();
    fireEvent.change(screen.getByLabelText('Generate tests from a test suite'), { target: { value: 's1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Download project (.zip)' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ workflow, target: 'langgraph', suite_id: 's1' });
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


describe('ExportCodeModal — targets', () => {
  const suites = [{ id: 's1', workflow_id: 'wf-1', name: 'Refund cases', case_count: 4, updated_at: 't' }];
  const open = async () => {
    fetchMock.mockResolvedValueOnce(json({ suites }));
    render(<ExportCodeModal workflow={workflow} onClose={vi.fn()} />);
    await screen.findByText('Refund cases (4 cases)');
  };
  const pick = (label: RegExp) => fireEvent.click(screen.getByLabelText(label));

  it('offers the three formats with LangGraph selected', async () => {
    await open();
    expect(screen.getByLabelText(/LangGraph \(Python\)/)).toBeChecked();
    expect(screen.getByLabelText(/Plain Python/)).not.toBeChecked();
    expect(screen.getByLabelText(/MCP tools/)).not.toBeChecked();
    expect(screen.getByText(/stops with an error instead of exploring every branch/)).toBeInTheDocument();
  });

  it('sends the chosen target and shows its notes and next steps', async () => {
    fetchMock.mockResolvedValueOnce(json({ suites })).mockResolvedValueOnce(zip('attachment; filename="support-bot-python.zip"'));
    vi.spyOn(download, 'downloadBlob').mockImplementation(() => undefined);
    await open();
    pick(/Plain Python/);
    expect(screen.getByText(/each step runs at most once per run/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Download project (.zip)' }));
    expect(await screen.findByRole('status')).toHaveTextContent('support-bot-python.zip downloaded');
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ workflow, target: 'python' });
  });

  it('hides the test-suite choice for MCP and never sends a suite with it', async () => {
    fetchMock.mockResolvedValueOnce(json({ suites })).mockResolvedValueOnce(zip('attachment; filename="support-bot-mcp.zip"'));
    vi.spyOn(download, 'downloadBlob').mockImplementation(() => undefined);
    await open();
    fireEvent.change(screen.getByLabelText('Generate tests from a test suite'), { target: { value: 's1' } });
    pick(/MCP tools/);
    expect(screen.queryByLabelText('Generate tests from a test suite')).toBeNull();
    expect(screen.getByText(/Only TOOL, API, DATABASE and knowledge-search steps become tools/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Download project (.zip)' }));
    expect(await screen.findByText(/AIFLOW_MOCK=1 python server.py/)).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ workflow, target: 'mcp' });   // the earlier suite choice is not sent
  });

  it('keeps the suite choice when switching between formats that support tests', async () => {
    fetchMock.mockResolvedValueOnce(json({ suites })).mockResolvedValueOnce(zip());
    vi.spyOn(download, 'downloadBlob').mockImplementation(() => undefined);
    await open();
    fireEvent.change(screen.getByLabelText('Generate tests from a test suite'), { target: { value: 's1' } });
    pick(/Plain Python/);
    expect(screen.getByLabelText('Generate tests from a test suite')).toHaveValue('s1');
    fireEvent.click(screen.getByRole('button', { name: 'Download project (.zip)' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ workflow, target: 'python', suite_id: 's1' });
  });

  it('shows the server reason when a target cannot be exported', async () => {
    fetchMock.mockResolvedValueOnce(json({ suites })).mockResolvedValueOnce(json({ detail: 'This workflow has no TOOL, API, DATABASE or RAG steps, so there is nothing to expose as an MCP tool.' }, 422));
    await open();
    pick(/MCP tools/);
    fireEvent.click(screen.getByRole('button', { name: 'Download project (.zip)' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('nothing to expose as an MCP tool');
  });
});
