import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ExportCodeModal } from './ExportCodeModal';
import { importLangGraph, readFiles } from '../../services/codeExport';
import { NodeType } from '../../models/workflow';
import type { Workflow } from '../../models/workflow';

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ session: { access_token: 'tok' } }),
}));

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
beforeEach(() => { fetchMock.mockReset(); vi.restoreAllMocks(); });

const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });

const workflow: Workflow = {
  version: '1.0', id: 'wf-1', name: 'Support Bot', description: '',
  nodes: [{ id: 's', type: NodeType.START, name: 'Start', position: { x: 0, y: 0 }, config: {} }], edges: [], metadata: {},
};

const imported = {
  workflow: {
    ...workflow, name: 'Imported',
    nodes: [
      { id: 's', type: NodeType.START, name: 'Start', position: { x: 0, y: 0 }, config: {} },
      { id: 'a', type: NodeType.LLM, name: 'A', position: { x: 0, y: 0 }, config: {} },
      { id: 'e', type: NodeType.END, name: 'End', position: { x: 0, y: 0 }, config: {} },
    ],
    edges: [{ source: 's', target: 'a' }, { source: 'a', target: 'e' }],
  },
  warnings: ['Step types were inferred from the code and may need correcting: a (LLM).'],
  mode: 'inferred' as const,
};

describe('importLangGraph / readFiles', () => {
  const file = (name: string, text: string) => new File([text], name, { type: 'text/plain' });

  it('posts the files and returns the workflow with its warnings', async () => {
    fetchMock.mockResolvedValue(json({ workflow, warnings: ['check types'], mode: 'inferred' }));
    const out = await importLangGraph('tok', { 'graph.py': 'code' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/workflows/import/langgraph');
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(JSON.parse(init.body)).toEqual({ files: { 'graph.py': 'code' } });
    expect(out).toEqual({ workflow, warnings: ['check types'], mode: 'inferred' });
  });

  it('turns a server refusal into a readable error', async () => {
    fetchMock.mockResolvedValue(json({ detail: 'No LangGraph StateGraph was found.' }, 422));
    await expect(importLangGraph('t', { 'a.py': 'x' })).rejects.toThrow('No LangGraph StateGraph was found.');
  });

  it('reads the text of chosen files by name', async () => {
    expect(await readFiles([file('graph.py', 'a = 1'), file('steps.py', 'b = 2')])).toEqual({ 'graph.py': 'a = 1', 'steps.py': 'b = 2' });
  });

  it('refuses too many or too large files before sending anything', async () => {
    await expect(readFiles(Array.from({ length: 21 }, (_, i) => file(`f${i}.py`, 'x')))).rejects.toThrow('at most 20 files');
    await expect(readFiles([file('big.py', 'x'.repeat(200_001))])).rejects.toThrow('big.py is too large');
  });
});

describe('ExportCodeModal — import tab', () => {
  const open = async (onImport = vi.fn(), onClose = vi.fn()) => {
    fetchMock.mockResolvedValueOnce(json({ suites: [] }));
    render(<ExportCodeModal workflow={workflow} onImport={onImport} onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: 'Import' }));
    return { onImport, onClose };
  };
  const read = () => fireEvent.click(screen.getByRole('button', { name: 'Read code' }));

  it('has no Import tab unless the caller can take a workflow', () => {
    fetchMock.mockResolvedValueOnce(json({ suites: [] }));
    render(<ExportCodeModal workflow={workflow} onClose={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Import' })).toBeNull();
  });

  it('needs some code before it can read anything', async () => {
    await open();
    expect(screen.getByRole('button', { name: 'Read code' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Import as workflow' })).toBeDisabled();
  });

  it('reads pasted code and shows what was found, with warnings', async () => {
    await open();
    fireEvent.change(screen.getByLabelText('Or paste code'), { target: { value: 'builder = StateGraph(dict)' } });
    fetchMock.mockResolvedValueOnce(json(imported));
    read();
    expect(await screen.findByTestId('import-summary')).toHaveTextContent('Read from the code: 3 steps, 2 edges.');
    expect(screen.getByText(/may need correcting: a \(LLM\)/)).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ files: { 'pasted.py': 'builder = StateGraph(dict)' } });
    expect(screen.getByRole('button', { name: 'Import as workflow' })).toBeEnabled();
  });

  it('reads uploaded files together with pasted code, and lets a file be removed', async () => {
    await open();
    fireEvent.change(screen.getByLabelText('Choose files'), { target: { files: [new File(['a = 1'], 'graph.py'), new File(['b = 2'], 'steps.py')] } });
    expect(await screen.findByLabelText('Remove graph.py')).toBeInTheDocument();       // waits until the files are read
    fireEvent.click(screen.getByLabelText('Remove steps.py'));
    expect(screen.queryByLabelText('Remove steps.py')).toBeNull();
    fireEvent.change(screen.getByLabelText('Or paste code'), { target: { value: 'c = 3' } });
    fetchMock.mockResolvedValueOnce(json(imported));
    read();
    await screen.findByTestId('import-summary');
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).files).toEqual({ 'graph.py': 'a = 1', 'pasted.py': 'c = 3' });
  });

  it('says when the upload was an AiFlow export', async () => {
    await open();
    fireEvent.change(screen.getByLabelText('Or paste code'), { target: { value: 'x' } });
    fetchMock.mockResolvedValueOnce(json({ ...imported, mode: 'exact', warnings: [] }));
    read();
    expect(await screen.findByTestId('import-summary')).toHaveTextContent('Restored from workflow.json');
  });

  it('imports with a layout applied and closes', async () => {
    const { onImport, onClose } = await open();
    fireEvent.change(screen.getByLabelText('Or paste code'), { target: { value: 'x' } });
    fetchMock.mockResolvedValueOnce(json(imported));
    read();
    await screen.findByTestId('import-summary');
    fireEvent.click(screen.getByRole('button', { name: 'Import as workflow' }));
    const loaded = onImport.mock.calls[0][0] as Workflow;
    expect(loaded.nodes.map((n) => n.id)).toEqual(['s', 'a', 'e']);
    expect(new Set(loaded.nodes.map((n) => `${n.position.x},${n.position.y}`)).size).toBe(3);   // laid out, not stacked at 0,0
    expect(onClose).toHaveBeenCalled();
  });

  it('shows the server reason and nothing to import when the code has no graph', async () => {
    const { onImport } = await open();
    fireEvent.change(screen.getByLabelText('Or paste code'), { target: { value: 'x = 1' } });
    fetchMock.mockResolvedValueOnce(json({ detail: 'No LangGraph StateGraph was found. Upload the file that builds the graph.' }, 422));
    read();
    expect(await screen.findByRole('alert')).toHaveTextContent('No LangGraph StateGraph was found');
    expect(screen.getByRole('button', { name: 'Import as workflow' })).toBeDisabled();
    expect(onImport).not.toHaveBeenCalled();
  });

  it('changing the code clears the previous result', async () => {
    await open();
    fireEvent.change(screen.getByLabelText('Or paste code'), { target: { value: 'x' } });
    fetchMock.mockResolvedValueOnce(json(imported));
    read();
    await screen.findByTestId('import-summary');
    fireEvent.change(screen.getByLabelText('Or paste code'), { target: { value: 'xy' } });
    expect(screen.queryByTestId('import-summary')).toBeNull();
    expect(screen.getByRole('button', { name: 'Import as workflow' })).toBeDisabled();
  });

  it('rejects oversized uploads with a message', async () => {
    await open();
    fireEvent.change(screen.getByLabelText('Choose files'), { target: { files: [new File(['x'.repeat(200_001)], 'huge.py')] } });
    expect(await screen.findByRole('alert')).toHaveTextContent('huge.py is too large');
  });
});
