import { describe, it, expect } from 'vitest';
import { mermaidId, mermaidToWorkflow, workflowToMermaid } from './mermaid';
import { NodeType } from '../models/workflow';
import type { Workflow } from '../models/workflow';
import { deserializeWorkflow } from '../utils/workflowSerializer';

import emailAutoReply from '../../../examples/easy/email-auto-reply.json';
import sentiment from '../../../examples/easy/sentiment-classifier.json';
import dataEnrichment from '../../../examples/easy/data-enrichment.json';
import customerSupport from '../../../examples/medium/customer-support.json';
import contentModeration from '../../../examples/medium/content-moderation.json';
import invoiceProcessing from '../../../examples/medium/invoice-processing.json';
import hrOnboarding from '../../../examples/medium/hr-onboarding.json';
import aiResearch from '../../../examples/complex/ai-research-agent.json';
import supplyChain from '../../../examples/complex/supply-chain-monitor.json';
import multiAgent from '../../../examples/complex/multi-agent-customer-journey.json';

const EXAMPLES: Record<string, unknown> = {
  emailAutoReply, sentiment, dataEnrichment, customerSupport, contentModeration, invoiceProcessing, hrOnboarding,
  aiResearch, supplyChain, multiAgent,
};

const wf = (nodes: Workflow['nodes'], edges: Workflow['edges'], name = 'Test'): Workflow => ({
  version: '1.0', id: 'w', name, description: '', nodes, edges, metadata: {},
});
const n = (id: string, type: NodeType, name = id): Workflow['nodes'][number] => ({ id, type, name, position: { x: 0, y: 0 }, config: {} });

describe('mermaidId', () => {
  it('sanitises, avoids reserved words and keeps ids unique', () => {
    const used = new Set<string>();
    expect(mermaidId('approval-check', used)).toBe('approval_check');
    expect(mermaidId('approval_check', used)).toBe('approval_check_2');      // collision after sanitising
    expect(mermaidId('end', used)).toBe('end_n');                             // `end` would close a subgraph
    expect(mermaidId('1st', used)).toBe('n_1st');
    expect(mermaidId('', used)).toBe('n_');
    expect(mermaidId('über node', used)).toBe('_ber_node');
  });
});

describe('workflowToMermaid', () => {
  const flow = wf(
    [n('start', NodeType.START, 'Start'), n('c', NodeType.CONDITION, 'Is "VIP"?'), n('db', NodeType.DATABASE, 'Orders'), n('e', NodeType.END, 'End')],
    [{ source: 'start', target: 'c' }, { source: 'c', target: 'db', condition: 'yes "sure"' }, { source: 'db', target: 'e' }],
    'My flow',
  );
  const text = workflowToMermaid(flow);

  it('writes a flowchart with the workflow name and shapes per type', () => {
    const lines = text.split('\n');
    expect(lines[0]).toBe('%% AiFlow workflow: My flow');
    expect(lines[1]).toBe('flowchart TD');
    expect(text).toContain('start(["Start"]):::START');
    expect(text).toContain('c{"Is #quot;VIP#quot;?"}:::CONDITION');
    expect(text).toContain('db[("Orders")]:::DATABASE');
    expect(text).toContain('e(["End"]):::END');
  });

  it('writes edges with escaped labels', () => {
    expect(text).toContain('start --> c');
    expect(text).toContain('c -->|"yes #quot;sure#quot;"| db');
  });

  it('styles only the types that are used', () => {
    expect(text).toContain('classDef START ');
    expect(text).toContain('classDef CONDITION ');
    expect(text).not.toContain('classDef LLM ');
  });

  it('survives empty workflows and multi-line names', () => {
    expect(workflowToMermaid(wf([], []))).toContain('flowchart TD');
    expect(workflowToMermaid(wf([n('a', NodeType.LLM, 'line one\nline two')], []))).toContain('"line one<br/>line two"');
  });

  it('skips edges that point at missing nodes', () => {
    const out = workflowToMermaid(wf([n('a', NodeType.START)], [{ source: 'a', target: 'ghost' }]));
    expect(out).not.toContain('-->');
  });
});

describe('mermaidToWorkflow — our own output', () => {
  it('imports an exported diagram back with the same types, names and edge labels', () => {
    const original = wf(
      [n('start', NodeType.START, 'Start'), n('l', NodeType.LLM, 'Classify'), n('c', NodeType.CONDITION, 'Decide'), n('h', NodeType.HITL, 'Review'),
       n('a', NodeType.API, 'Call CRM'), n('t', NodeType.TOOL, 'Search'), n('r', NodeType.RAG, 'Docs'), n('x', NodeType.TRANSFORM, 'Shape'), n('e', NodeType.END, 'End')],
      [{ source: 'start', target: 'l' }, { source: 'l', target: 'c' }, { source: 'c', target: 'h', condition: 'complex' }, { source: 'c', target: 'a', condition: 'simple' },
       { source: 'h', target: 't' }, { source: 't', target: 'r' }, { source: 'r', target: 'x' }, { source: 'a', target: 'x' }, { source: 'x', target: 'e' }],
      'Round trip',
    );
    const { workflow, errors } = mermaidToWorkflow(workflowToMermaid(original));
    expect(errors).toEqual([]);
    expect(workflow!.name).toBe('Round trip');
    expect(workflow!.nodes.map((x) => [x.id, x.type, x.name])).toEqual(original.nodes.map((x) => [x.id, x.type, x.name]));
    expect(workflow!.edges).toEqual(original.edges);
    expect(workflow!.nodes.every((x) => Object.keys(x.config).length === 0)).toBe(true);
  });

  it('lays the imported nodes out', () => {
    const { workflow } = mermaidToWorkflow(workflowToMermaid(wf([n('s', NodeType.START), n('e', NodeType.END)], [{ source: 's', target: 'e' }])));
    const [s, e] = workflow!.nodes;
    expect(e.position.y).toBeGreaterThan(s.position.y);
  });

  it.each(Object.keys(EXAMPLES))('round-trips example %s', (key) => {
    const original = deserializeWorkflow(JSON.stringify(EXAMPLES[key]));
    const text = workflowToMermaid(original);
    const { workflow, errors, warnings } = mermaidToWorkflow(text);
    expect(errors).toEqual([]);
    expect(warnings.some((w) => /was added|guessed|could not be told/.test(w))).toBe(false);   // nothing had to be invented
    expect(workflow!.nodes.map((x) => x.type)).toEqual(original.nodes.map((x) => x.type));
    expect(workflow!.nodes.map((x) => x.name)).toEqual(original.nodes.map((x) => x.name));
    // ids are rewritten to be Mermaid-safe (hyphens, reserved words such as `end`); everything else is kept
    const used = new Set<string>();
    const mapped = new Map(original.nodes.map((x) => [x.id, mermaidId(x.id, used)]));
    expect(workflow!.nodes.map((x) => x.id)).toEqual(original.nodes.map((x) => mapped.get(x.id)));
    expect(workflow!.edges.map((e) => [e.source, e.target, e.condition])).toEqual(
      original.edges.map((e) => [mapped.get(e.source), mapped.get(e.target), e.condition]),
    );
    expect(workflowToMermaid(workflow!)).toBe(text);   // stable: exporting the import gives the same diagram
  });
});

describe('mermaidToWorkflow — hand-written diagrams', () => {
  it('reads common syntax and infers types from shapes and labels', () => {
    const { workflow, errors, warnings } = mermaidToWorkflow(`
      graph LR
        S((Start)) --> Q{Is it urgent?}
        Q -- yes --> H[Handle now]
        Q -->|no| L([Log it])
        H --> DB[(Tickets)]
        L --> DB
        DB --> F((Finish))
    `);
    expect(errors).toEqual([]);
    const byId = Object.fromEntries(workflow!.nodes.map((x) => [x.id, x.type]));
    expect(byId).toEqual({ S: NodeType.START, Q: NodeType.CONDITION, H: NodeType.TRANSFORM, L: NodeType.TRANSFORM, DB: NodeType.DATABASE, F: NodeType.END });
    expect(workflow!.edges.filter((e) => e.condition).map((e) => [e.target, e.condition])).toEqual([['H', 'yes'], ['L', 'no']]);
    expect(warnings.join(' ')).toMatch(/could not be told from the diagram for: Handle now, Log it/);
    expect(workflow!.nodes.find((x) => x.id === 'Q')!.name).toBe('Is it urgent?');
  });

  it('supports chains, & groups, semicolons, comments and several link styles', () => {
    const { workflow, errors } = mermaidToWorkflow(`flowchart TD
      %% a comment
      a((Start)) --> b[One] ==> c[Two]; b -.-> d[Three]
      c & d --> e((End))   %% trailing comment
      a --- e
      b -. maybe .-> e
    `);
    expect(errors).toEqual([]);
    const pairs = workflow!.edges.map((e) => `${e.source}>${e.target}${e.condition ? `:${e.condition}` : ''}`);
    expect(pairs).toEqual(expect.arrayContaining(['a>b', 'b>c', 'b>d', 'c>e', 'd>e', 'a>e', 'b>e:maybe']));
  });

  it('applies :::Type classes and `class` statements, case-insensitively', () => {
    const { workflow } = mermaidToWorkflow(`flowchart TD
      s[Begin]:::start --> a[Ask]:::llm --> b[Fetch]
      class b api
      b --> e[Done]:::END`);
    expect(Object.fromEntries(workflow!.nodes.map((x) => [x.id, x.type]))).toEqual({
      s: NodeType.START, a: NodeType.LLM, b: NodeType.API, e: NodeType.END,
    });
  });

  it('ignores styling statements and front-matter titles, and reads quoted labels', () => {
    const { workflow, errors } = mermaidToWorkflow(`---
title: Support flow
---
flowchart TD
  a(["Start"]) --> b["Say <br/> hello #quot;there#quot;"]
  style b fill:#f9f
  linkStyle 0 stroke:red
  classDef x fill:#fff
  click b callback
  b --> c(["End"])`);
    expect(errors).toEqual([]);
    expect(workflow!.name).toBe('Support flow');
    expect(workflow!.nodes.find((x) => x.id === 'b')!.name).toBe('Say hello "there"');
  });

  it('adds a START and an END when the diagram has none worth using', () => {
    const { workflow, warnings } = mermaidToWorkflow(`flowchart TD
      a[Step A]:::LLM --> c[Step C]:::API
      b[Step B]:::LLM --> c`);
    const types = workflow!.nodes.map((x) => x.type);
    expect(types.filter((t) => t === NodeType.START)).toHaveLength(1);
    expect(types.filter((t) => t === NodeType.END)).toHaveLength(1);
    const start = workflow!.nodes.find((x) => x.type === NodeType.START)!;
    expect(workflow!.edges.filter((e) => e.source === start.id).map((e) => e.target).sort()).toEqual(['a', 'b']);
    expect(warnings.join(' ')).toMatch(/no START node, so one was added/);
    expect(warnings.join(' ')).toMatch(/no END node, so one was added/);
  });

  it('promotes a lone untyped root and leaf to START and END', () => {
    const { workflow, warnings } = mermaidToWorkflow('flowchart TD\n  a[Begin here] --> b[Middle] --> c[Finish up]');
    expect(workflow!.nodes.map((x) => x.type)).toEqual([NodeType.START, NodeType.TRANSFORM, NodeType.END]);
    expect(warnings.join(' ')).toMatch(/used as the START/);
  });

  it('warns that subgraphs are flattened and that settings are not carried', () => {
    const { workflow, warnings } = mermaidToWorkflow(`flowchart TD
      s((Start)) --> a
      subgraph Group
        a[Inside]
      end
      a --> e((End))`);
    expect(workflow!.nodes.map((x) => x.id)).toEqual(['s', 'a', 'e']);
    expect(warnings.join(' ')).toMatch(/Subgraphs are not supported/);
    expect(warnings.join(' ')).toMatch(/does not carry node settings/);
  });
});

describe('statement splitting', () => {
  it('keeps semicolons that belong to quoted labels and entities', () => {
    const { workflow, errors } = mermaidToWorkflow('flowchart TD\n  a(["Start"]):::START --> b["x; y #quot;z#quot;"]:::LLM; b --> c([End]):::END');
    expect(errors).toEqual([]);
    expect(workflow!.nodes.find((x) => x.id === 'b')!.name).toBe('x; y "z"');
    expect(workflow!.edges).toHaveLength(2);
  });

  it('round-trips names that contain quotes and semicolons', () => {
    const w = wf([n('s', NodeType.START), n('x', NodeType.LLM, 'say "hi"; then leave'), n('e', NodeType.END)],
      [{ source: 's', target: 'x', condition: 'a;b "c"' }, { source: 'x', target: 'e' }]);
    const { workflow, errors } = mermaidToWorkflow(workflowToMermaid(w));
    expect(errors).toEqual([]);
    expect(workflow!.nodes[1].name).toBe('say "hi"; then leave');
    expect(workflow!.edges[0].condition).toBe('a;b "c"');
  });
});

describe('mermaidToWorkflow — problems', () => {
  it.each([
    ['', /empty/i],
    ['hello world', /does not look like a Mermaid flowchart/],
    ['sequenceDiagram\n A->>B: hi', /does not look like a Mermaid flowchart/],
    ['flowchart TD', /has no nodes/],
  ])('rejects %j', (text, pattern) => {
    const { workflow, errors } = mermaidToWorkflow(text);
    expect(workflow).toBeUndefined();
    expect(errors.join(' ')).toMatch(pattern);
  });

  it('reports syntax errors with line numbers instead of guessing', () => {
    const { workflow, errors } = mermaidToWorkflow('flowchart TD\n  a[Start --> b\n  c((x)) ~~~ d');
    expect(workflow).toBeUndefined();
    expect(errors.length).toBeGreaterThan(0);
    expect(errors[0]).toMatch(/^Line 2:/);
  });

  it('rejects more than one START', () => {
    const { errors } = mermaidToWorkflow('flowchart TD\n  a((Start)) --> c[X]\n  b((Begin)) --> c');
    expect(errors.join(' ')).toMatch(/2 START nodes/);
  });

  it('enforces size limits', () => {
    const many = 'flowchart TD\n' + Array.from({ length: 101 }, (_, i) => `  n${i}[N${i}]`).join('\n');
    expect(mermaidToWorkflow(many).errors.join(' ')).toMatch(/101 nodes; the limit is 100/);
    expect(mermaidToWorkflow('x'.repeat(100_001)).errors.join(' ')).toMatch(/too large/);
  });

  it('never throws on hostile or random input', () => {
    for (const text of ['flowchart TD\n a[', 'flowchart TD\n a["unterminated', 'flowchart TD\n -->', 'flowchart TD\n a --> ', '((((', 'graph\n&&&', '\u0000\u0001', 'flowchart TD\n a{{x}} --> b[(y)]\n']) {
      expect(() => mermaidToWorkflow(text)).not.toThrow();
    }
  });
});
