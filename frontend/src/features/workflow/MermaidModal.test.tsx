import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MermaidModal } from './MermaidModal';
import { Toolbar } from '../../components/Toolbar';
import { NodeType } from '../../models/workflow';
import type { Workflow } from '../../models/workflow';
import * as download from '../../utils/download';

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ session: { access_token: 'tok' }, profile: { role: 'user', email: 'a@b.c' }, user: null, signOut: vi.fn() }),
}));

const workflow: Workflow = {
  version: '1.0', id: 'w', name: 'Support Bot', description: '',
  nodes: [
    { id: 'start', type: NodeType.START, name: 'Start', position: { x: 0, y: 0 }, config: {} },
    { id: 'end', type: NodeType.END, name: 'End', position: { x: 0, y: 1 }, config: {} },
  ],
  edges: [{ source: 'start', target: 'end' }],
  metadata: {},
};

beforeEach(() => vi.restoreAllMocks());

const setup = () => {
  const onImport = vi.fn();
  const onClose = vi.fn();
  render(<MermaidModal workflow={workflow} onImport={onImport} onClose={onClose} />);
  return { onImport, onClose };
};

describe('MermaidModal — export', () => {
  it('shows the diagram for the current workflow', () => {
    setup();
    const text = (screen.getByLabelText('Mermaid diagram') as HTMLTextAreaElement).value;
    expect(text).toContain('flowchart TD');
    expect(text).toContain('start(["Start"]):::START');
    expect(text).toContain('end_n(["End"]):::END');         // `end` is a reserved word in Mermaid
    expect(text).toContain('start --> end_n');
  });

  it('copies to the clipboard and says so, or explains when blocked', async () => {
    const spy = vi.spyOn(download, 'copyText').mockResolvedValue(true);
    setup();
    fireEvent.click(screen.getByText('Copy'));
    expect(await screen.findByText('Copied')).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith(expect.stringContaining('flowchart TD'));

    spy.mockResolvedValue(false);
    fireEvent.click(screen.getByText('Copy'));
    expect(await screen.findByText(/blocked by the browser/)).toBeInTheDocument();
  });

  it('downloads a .mmd file named after the workflow', () => {
    const spy = vi.spyOn(download, 'downloadText').mockImplementation(() => undefined);
    setup();
    fireEvent.click(screen.getByText('Download .mmd'));
    expect(spy).toHaveBeenCalledWith(expect.stringContaining('flowchart TD'), 'support-bot.mmd', 'text/vnd.mermaid');
  });
});

describe('MermaidModal — import', () => {
  const goToImport = () => fireEvent.click(screen.getByRole('button', { name: 'Import' }));

  it('starts disabled and previews a valid diagram', () => {
    setup();
    goToImport();
    expect(screen.getByRole('button', { name: 'Import as workflow' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Mermaid source'), { target: { value: 'flowchart TD\n  s((Start)) --> a[Do it]\n  a --> e((End))' } });
    expect(screen.getByTestId('import-summary')).toHaveTextContent('3 nodes, 2 edges');
    expect(screen.getByText(/could not be told from the diagram for: Do it/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import as workflow' })).toBeEnabled();
  });

  it('shows errors and keeps the button disabled', () => {
    setup();
    goToImport();
    fireEvent.change(screen.getByLabelText('Mermaid source'), { target: { value: 'sequenceDiagram\n A->>B: hi' } });
    expect(screen.getByRole('alert')).toHaveTextContent(/does not look like a Mermaid flowchart/);
    expect(screen.getByRole('button', { name: 'Import as workflow' })).toBeDisabled();
  });

  it('hands the imported workflow to the caller and closes', () => {
    const { onImport, onClose } = setup();
    goToImport();
    fireEvent.change(screen.getByLabelText('Mermaid source'), { target: { value: 'flowchart TD\n  s((Start)) --> e((End))' } });
    fireEvent.click(screen.getByRole('button', { name: 'Import as workflow' }));
    expect(onImport).toHaveBeenCalledTimes(1);
    const imported = onImport.mock.calls[0][0] as Workflow;
    expect(imported.nodes.map((n) => n.type)).toEqual([NodeType.START, NodeType.END]);
    expect(onClose).toHaveBeenCalled();
  });

  it('closes on Escape', () => {
    const { onClose } = setup();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});

describe('Toolbar — Mermaid button', () => {
  it('opens the modal handler', () => {
    const onMermaid = vi.fn();
    render(<Toolbar workflowName="W" onNew={vi.fn()} onSave={vi.fn()} onOpen={vi.fn()} onOpenExamplePicker={vi.fn()} onValidate={vi.fn()}
      onGenerate={vi.fn()} onRefine={vi.fn()} onSimulate={vi.fn()} onEditJson={vi.fn()} onNameChange={vi.fn()} onMermaid={onMermaid} />);
    fireEvent.click(screen.getByRole('button', { name: 'Mermaid' }));
    expect(onMermaid).toHaveBeenCalledOnce();
  });
});
