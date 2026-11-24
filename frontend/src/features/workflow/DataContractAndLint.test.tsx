import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ValidationPanel } from './ValidationPanel';
import { PropertiesPanel } from './PropertiesPanel';
import { WorkflowNodeComponent } from './nodes/WorkflowNodeComponent';
import { updateNodeSchema } from './WorkflowAdapter';
import { NodeType } from '../../models/workflow';
import type { Workflow } from '../../models/workflow';
import type { LintResult } from '../../models/lint';

vi.mock('@xyflow/react', () => ({
  Handle: () => null,
  Position: { Top: 'top', Bottom: 'bottom' },
}));

const lint: LintResult = {
  findings: [
    { rule_id: 'no-failure-branch', severity: 'warning', node_id: 'api-1', message: "'Fetch' has no failure branch.", fix_hint: 'Add a CONDITION.' },
    { rule_id: 'cycle', severity: 'warning', node_id: null, message: 'Cycle detected.', fix_hint: '' },
  ],
  estimates: [{ node_ids: ['s', 'e'], node_names: ['Start', 'End'], latency_ms: 2000, cost_usd: 0.002 }],
};

describe('ValidationPanel — lint findings', () => {
  const result = { valid: true, errors: [], warnings: [] };

  it('lists findings with hint, rule id and estimate summary', () => {
    render(<ValidationPanel result={result} lint={lint} onSelectNode={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.getByText(/design findings \(2\)/i)).toBeInTheDocument();
    expect(screen.getByText(/has no failure branch/)).toBeInTheDocument();
    expect(screen.getByText(/Add a CONDITION/)).toBeInTheDocument();
    expect(screen.getByText(/\[no-failure-branch\]/)).toBeInTheDocument();
    expect(screen.getByText(/1 path/)).toBeInTheDocument();
  });

  it('selects the node when a finding is clicked; node-less findings are not clickable', () => {
    const onSelectNode = vi.fn();
    render(<ValidationPanel result={result} lint={lint} onSelectNode={onSelectNode} onDismiss={vi.fn()} />);
    fireEvent.click(screen.getByText(/has no failure branch/));
    expect(onSelectNode).toHaveBeenCalledWith('api-1');
    expect(screen.getByText(/Cycle detected/).closest('button')).toBeDisabled();
  });

  it('renders nothing extra without lint data', () => {
    render(<ValidationPanel result={result} lint={null} onDismiss={vi.fn()} />);
    expect(screen.queryByText(/design findings/i)).toBeNull();
  });
});

describe('WorkflowNodeComponent — lint badge', () => {
  const props = (lintData?: { severity: 'warning'; count: number; title: string }) => ({
    data: { label: 'N', nodeType: NodeType.LLM, config: {}, lint: lintData },
    selected: false,
  } as Parameters<typeof WorkflowNodeComponent>[0]);

  it('shows the count and tooltip', () => {
    render(<WorkflowNodeComponent {...props({ severity: 'warning', count: 3, title: 'a\nb\nc' })} />);
    const badge = screen.getByTestId('lint-badge');
    expect(badge).toHaveTextContent('3');
    expect(badge).toHaveClass('node-lint-badge--warning');
    expect(badge).toHaveAttribute('title', 'a\nb\nc');
  });

  it('shows no badge without findings', () => {
    render(<WorkflowNodeComponent {...props(undefined)} />);
    expect(screen.queryByTestId('lint-badge')).toBeNull();
  });
});

function makeWorkflow(): Workflow {
  return {
    version: '1.0', id: 'wf', name: 'T', description: '',
    nodes: [
      { id: 'start', type: NodeType.START, name: 'Start', position: { x: 0, y: 0 }, config: {} },
      { id: 'llm-1', type: NodeType.LLM, name: 'My LLM', position: { x: 0, y: 100 }, config: { prompt: 'p' }, output_schema: { type: 'object' } },
      { id: 'cond', type: NodeType.CONDITION, name: 'Cond', position: { x: 0, y: 200 }, config: { expression: 'x' } },
    ],
    edges: [],
  };
}

describe('updateNodeSchema', () => {
  it('sets and removes a schema without touching other nodes', () => {
    const wf = makeWorkflow();
    const set = updateNodeSchema(wf, 'llm-1', 'input_schema', { type: 'object' });
    expect(set.nodes[1].input_schema).toEqual({ type: 'object' });
    expect(set.nodes[1].output_schema).toEqual({ type: 'object' });
    expect(set.nodes[0]).toBe(wf.nodes[0]);

    const removed = updateNodeSchema(set, 'llm-1', 'output_schema', undefined);
    expect('output_schema' in removed.nodes[1]).toBe(false);
    expect(removed.nodes[1].input_schema).toEqual({ type: 'object' });
  });
});

describe('PropertiesPanel — data contract', () => {
  const renderPanel = (nodeId: string, onSchemaChange = vi.fn(), onConfigChange = vi.fn()) => {
    render(
      <PropertiesPanel
        workflow={makeWorkflow()}
        selectedNodeId={nodeId}
        selectedEdgeId={null}
        onNameChange={vi.fn()}
        onConfigChange={onConfigChange}
        onSchemaChange={onSchemaChange}
        onEdgeChange={vi.fn()}
      />,
    );
    return { onSchemaChange, onConfigChange };
  };

  it('shows the existing output schema and edits input schema', () => {
    const { onSchemaChange } = renderPanel('llm-1');
    expect((screen.getByLabelText('Output schema') as HTMLTextAreaElement).value).toContain('"type": "object"');
    fireEvent.change(screen.getByLabelText('Input schema'), { target: { value: '{"type":"object","properties":{"id":{"type":"string"}}}' } });
    expect(onSchemaChange).toHaveBeenCalledWith('llm-1', 'input_schema', { type: 'object', properties: { id: { type: 'string' } } });
  });

  it('does not save invalid JSON', () => {
    const { onSchemaChange } = renderPanel('llm-1');
    fireEvent.change(screen.getByLabelText('Input schema'), { target: { value: '{oops' } });
    expect(onSchemaChange).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('pins mock output through node config', () => {
    const { onConfigChange } = renderPanel('llm-1');
    fireEvent.change(screen.getByLabelText('Mock output'), { target: { value: '{"tier":"premium"}' } });
    expect(onConfigChange).toHaveBeenCalledWith('llm-1', 'mock_output', { tier: 'premium' });
  });

  it('is hidden for START and CONDITION nodes', () => {
    renderPanel('start');
    expect(screen.queryByLabelText('Output schema')).toBeNull();
  });

  it('is hidden for CONDITION nodes', () => {
    renderPanel('cond');
    expect(screen.queryByLabelText('Input schema')).toBeNull();
  });
});
