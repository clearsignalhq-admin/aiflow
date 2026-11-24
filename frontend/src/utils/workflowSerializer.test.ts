import { describe, it, expect } from 'vitest';
import {
  serializeWorkflow,
  deserializeWorkflow,
  createDefaultWorkflow,
  MAX_NODES,
  MAX_EDGES,
  MAX_IMPORT_BYTES,
} from './workflowSerializer';
import { NodeType } from '../models/workflow';
import type { Workflow } from '../models/workflow';

describe('createDefaultWorkflow', () => {
  it('creates a workflow with START and END nodes', () => {
    const wf = createDefaultWorkflow();
    expect(wf.nodes).toHaveLength(2);
    expect(wf.nodes[0].type).toBe(NodeType.START);
    expect(wf.nodes[1].type).toBe(NodeType.END);
  });

  it('creates a START → END edge', () => {
    const wf = createDefaultWorkflow();
    expect(wf.edges).toHaveLength(1);
    expect(wf.edges[0].source).toBe('start');
    expect(wf.edges[0].target).toBe('end');
  });

  it('applies overrides', () => {
    const wf = createDefaultWorkflow({ name: 'My Workflow' });
    expect(wf.name).toBe('My Workflow');
  });

  it('sets version to 1.0', () => {
    const wf = createDefaultWorkflow();
    expect(wf.version).toBe('1.0');
  });
});

describe('serializeWorkflow / deserializeWorkflow', () => {
  it('round-trips a workflow without data loss', () => {
    const original = createDefaultWorkflow({ name: 'Round-trip test' });
    const json = serializeWorkflow(original);
    const loaded = deserializeWorkflow(json);
    expect(loaded.name).toBe('Round-trip test');
    expect(loaded.id).toBe(original.id);
    expect(loaded.nodes).toHaveLength(2);
    expect(loaded.edges).toHaveLength(1);
  });

  it('produces human-readable JSON (indented)', () => {
    const wf = createDefaultWorkflow();
    const json = serializeWorkflow(wf);
    expect(json).toContain('\n');
    expect(json).toContain('  ');
  });
});

describe('deserializeWorkflow error handling', () => {
  it('throws on invalid JSON', () => {
    expect(() => deserializeWorkflow('not json')).toThrow('Invalid JSON');
  });

  it('throws when root is not an object', () => {
    expect(() => deserializeWorkflow('"a string"')).toThrow('root must be an object');
  });

  it('throws when version is missing', () => {
    const data = { id: '1', name: 'x', nodes: [], edges: [] };
    expect(() => deserializeWorkflow(JSON.stringify(data))).toThrow('version');
  });

  it('throws when nodes is not an array', () => {
    const data = { version: '1.0', id: '1', name: 'x', nodes: null, edges: [] };
    expect(() => deserializeWorkflow(JSON.stringify(data))).toThrow('"nodes"');
  });

  it('throws on unknown node type', () => {
    const wf = createDefaultWorkflow();
    const data: Workflow = {
      ...wf,
      nodes: [{ id: 'n1', type: 'BOGUS' as NodeType, name: 'Bad', position: { x: 0, y: 0 }, config: {} }],
    };
    expect(() => deserializeWorkflow(JSON.stringify(data))).toThrow('unknown node type');
  });
});

describe('deserializeWorkflow size limits', () => {
  const base = () => createDefaultWorkflow();

  it('rejects files larger than the import limit', () => {
    expect(() => deserializeWorkflow(' '.repeat(MAX_IMPORT_BYTES + 1))).toThrow('too large');
  });

  it('rejects too many nodes', () => {
    const wf = base();
    wf.nodes = Array.from({ length: MAX_NODES + 1 }, (_, i) => ({ ...wf.nodes[0], id: `n${i}` }));
    expect(() => deserializeWorkflow(JSON.stringify(wf))).toThrow('too many nodes');
  });

  it('rejects too many edges', () => {
    const wf = base();
    wf.edges = Array.from({ length: MAX_EDGES + 1 }, () => ({ source: 'start', target: 'end' }));
    expect(() => deserializeWorkflow(JSON.stringify(wf))).toThrow('too many edges');
  });

  it('accepts a workflow at the limits', () => {
    const wf = base();
    wf.nodes = Array.from({ length: MAX_NODES }, (_, i) => ({ ...wf.nodes[0], id: `n${i}` }));
    expect(() => deserializeWorkflow(JSON.stringify(wf))).not.toThrow();
  });
});
