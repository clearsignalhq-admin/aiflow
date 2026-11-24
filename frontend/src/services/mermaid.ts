import { NodeType } from '../models/workflow';
import type { Workflow, WorkflowEdge, WorkflowNode } from '../models/workflow';
import { getNodeDefinition } from '../features/workflow/nodes/nodeDefinitions';
import { autoLayoutWorkflow } from '../features/workflow/WorkflowAdapter';
import { MAX_EDGES, MAX_NODES } from '../utils/workflowSerializer';

/**
 * Mermaid flowchart export and import.
 *
 * Mermaid is a *diagram* format: it carries the shape of the workflow (node types, names, edges and
 * their labels) but not node settings (prompts, URLs, expressions, schemas). Export is therefore
 * lossy by design, and import produces nodes with empty configuration.
 *
 * Node types are written as a Mermaid class (`id["Name"]:::LLM`) plus a shape, so a diagram produced
 * here imports back exactly. Hand-written diagrams are accepted too; their types are inferred from
 * the shape and label, and anything guessed is reported as a warning.
 */

export const MAX_MERMAID_CHARS = 100_000;

// ═════════════════════════════ Export ═════════════════════════════

const RESERVED = new Set([
  'end', 'graph', 'flowchart', 'subgraph', 'style', 'class', 'classdef', 'click', 'default',
  'direction', 'linkstyle', 'call', 'href',
]);

/** [open, close] Mermaid shape delimiters per node type. */
const SHAPES: Record<NodeType, [string, string]> = {
  [NodeType.START]: ['([', '])'],
  [NodeType.END]: ['([', '])'],
  [NodeType.LLM]: ['[', ']'],
  [NodeType.TOOL]: ['[[', ']]'],
  [NodeType.API]: ['[/', '/]'],
  [NodeType.DATABASE]: ['[(', ')]'],
  [NodeType.RAG]: ['{{', '}}'],
  [NodeType.CONDITION]: ['{', '}'],
  [NodeType.HITL]: ['((', '))'],
  [NodeType.TRANSFORM]: ['[', ']'],
};

function escapeLabel(text: string): string {
  return text.replace(/"/g, '#quot;').replace(/\r?\n/g, '<br/>');
}

function unescapeLabel(text: string): string {
  return text
    .replace(/\s*<br\s*\/?>\s*/gi, ' ')
    .replace(/#quot;/g, '"')
    .replace(/#amp;/g, '&')
    .replace(/#lt;/g, '<')
    .replace(/#gt;/g, '>')
    .trim();
}

export function mermaidId(id: string, used: Set<string>): string {
  let base = id.replace(/[^A-Za-z0-9_]/g, '_');
  if (!base || /^[0-9]/.test(base)) base = `n_${base}`;
  if (RESERVED.has(base.toLowerCase())) base = `${base}_n`;
  let candidate = base;
  for (let i = 2; used.has(candidate); i++) candidate = `${base}_${i}`;
  used.add(candidate);
  return candidate;
}

export function workflowToMermaid(workflow: Workflow): string {
  const used = new Set<string>();
  const ids = new Map<string, string>();
  for (const n of workflow.nodes) ids.set(n.id, mermaidId(n.id, used));

  const lines: string[] = [];
  lines.push(`%% AiFlow workflow: ${workflow.name.replace(/[\r\n]+/g, ' ')}`);
  lines.push('flowchart TD');

  for (const n of workflow.nodes) {
    const [open, close] = SHAPES[n.type];
    lines.push(`  ${ids.get(n.id)}${open}"${escapeLabel(n.name)}"${close}:::${n.type}`);
  }
  for (const e of workflow.edges) {
    const from = ids.get(e.source);
    const to = ids.get(e.target);
    if (!from || !to) continue;
    const label = e.condition?.trim();
    lines.push(label ? `  ${from} -->|"${escapeLabel(label)}"| ${to}` : `  ${from} --> ${to}`);
  }

  const usedTypes = new Set(workflow.nodes.map((n) => n.type));
  for (const type of Object.values(NodeType)) {
    if (!usedTypes.has(type)) continue;
    const def = getNodeDefinition(type);
    lines.push(`  classDef ${type} fill:${def.color},stroke:${def.color},color:${def.textColor}`);
  }
  return lines.join('\n') + '\n';
}

// ═════════════════════════════ Import ═════════════════════════════

export interface MermaidImportResult {
  workflow?: Workflow;
  errors: string[];
  warnings: string[];
}

type Shape = 'stadium' | 'subroutine' | 'cylinder' | 'parallelogram' | 'circle' | 'hexagon' | 'rhombus' | 'round' | 'rect' | 'asymmetric';

/** Longest openers first so `([` wins over `(` and `[[` over `[`. */
const OPENERS: { open: string; closes: string[]; shape: Shape }[] = [
  { open: '([', closes: ['])'], shape: 'stadium' },
  { open: '[[', closes: [']]'], shape: 'subroutine' },
  { open: '[(', closes: [')]'], shape: 'cylinder' },
  { open: '[/', closes: ['/]', '\\]'], shape: 'parallelogram' },
  { open: '[\\', closes: ['\\]', '/]'], shape: 'parallelogram' },
  { open: '((', closes: ['))'], shape: 'circle' },
  { open: '{{', closes: ['}}'], shape: 'hexagon' },
  { open: '{', closes: ['}'], shape: 'rhombus' },
  { open: '(', closes: [')'], shape: 'round' },
  { open: '[', closes: [']'], shape: 'rect' },
  { open: '>', closes: [']'], shape: 'asymmetric' },
];

const SHAPE_TYPE: Partial<Record<Shape, NodeType>> = {
  subroutine: NodeType.TOOL,
  cylinder: NodeType.DATABASE,
  parallelogram: NodeType.API,
  hexagon: NodeType.RAG,
  rhombus: NodeType.CONDITION,
};

const IGNORED_LINE = /^(classDef|style|linkStyle|click|direction|accTitle|accDescr)\b/i;
const START_LABEL = /^(start|begin|entry)\b/i;
const END_LABEL = /^(end|finish|finished|stop|done|exit)\b/i;

interface ParsedNode {
  id: string;
  label?: string;
  shape?: Shape;
  cls?: string;
}

interface DraftNode {
  id: string;
  name: string;
  type: NodeType;
  /** The type was inferred rather than stated, so it may be replaced when a START/END is needed. */
  guessed: boolean;
}

class Scanner {
  pos = 0;
  readonly text: string;
  constructor(text: string) {
    this.text = text;
  }

  skipSpaces() {
    while (this.pos < this.text.length && /\s/.test(this.text[this.pos])) this.pos++;
  }

  done() {
    this.skipSpaces();
    return this.pos >= this.text.length;
  }

  rest() {
    return this.text.slice(this.pos);
  }
}

function parseNode(sc: Scanner): ParsedNode | null {
  sc.skipSpaces();
  const idMatch = /^[A-Za-z0-9_À-￿]+/.exec(sc.rest());
  if (!idMatch) return null;
  const node: ParsedNode = { id: idMatch[0] };
  sc.pos += idMatch[0].length;

  const rest = sc.rest();
  const opener = OPENERS.find((o) => rest.startsWith(o.open));
  if (opener) {
    let body = rest.slice(opener.open.length);
    let label: string | undefined;
    let consumed = opener.open.length;
    if (body.startsWith('"')) {
      const end = body.indexOf('"', 1);
      if (end === -1) throw new Error(`Unterminated quote in the label of "${node.id}".`);
      label = body.slice(1, end);
      const after = body.slice(end + 1);
      const close = opener.closes.find((c) => after.startsWith(c));
      if (!close) throw new Error(`Expected "${opener.closes[0]}" after the label of "${node.id}".`);
      consumed += end + 1 + close.length;
    } else {
      let bestIndex = -1;
      let bestClose = '';
      for (const c of opener.closes) {
        const i = body.indexOf(c);
        if (i !== -1 && (bestIndex === -1 || i < bestIndex)) { bestIndex = i; bestClose = c; }
      }
      if (bestIndex === -1) throw new Error(`Missing "${opener.closes[0]}" for node "${node.id}".`);
      label = body.slice(0, bestIndex);
      body = '';
      consumed += bestIndex + bestClose.length;
    }
    node.label = unescapeLabel(label);
    node.shape = opener.shape;
    sc.pos += consumed;
  }

  const cls = /^:::([A-Za-z0-9_-]+)/.exec(sc.rest());
  if (cls) {
    node.cls = cls[1];
    sc.pos += cls[0].length;
  }
  return node;
}

interface Link { label?: string }

const LINK_WITH_TEXT = /^(--|==|-\.)\s+(.+?)\s+(-->|==>|\.->|---|===|\.-)/;
const LINK_PLAIN = /^<?(-{2,}>|-{3,}|={2,}>|={3,}|-\.+->|-\.+-|--[xo])/;

function parseLink(sc: Scanner): Link | null {
  sc.skipSpaces();
  const rest = sc.rest();
  let label: string | undefined;
  const withText = LINK_WITH_TEXT.exec(rest);
  if (withText) {
    label = withText[2];
    sc.pos += withText[0].length;
  } else {
    const plain = LINK_PLAIN.exec(rest);
    if (!plain) return null;
    sc.pos += plain[0].length;
  }
  const pipe = /^\s*\|\s*(.*?)\s*\|/.exec(sc.rest());
  if (pipe) {
    label = pipe[1];
    sc.pos += pipe[0].length;
  }
  if (label !== undefined) {
    label = unescapeLabel(label.replace(/^"(.*)"$/, '$1'));
  }
  return { label: label || undefined };
}

function parseNodeGroup(sc: Scanner): ParsedNode[] {
  const nodes: ParsedNode[] = [];
  for (;;) {
    const node = parseNode(sc);
    if (!node) throw new Error(`Could not read a node near "${sc.rest().slice(0, 20)}".`);
    nodes.push(node);
    sc.skipSpaces();
    if (sc.rest().startsWith('&')) { sc.pos += 1; continue; }
    return nodes;
  }
}

function typeFromClass(cls: string | undefined): NodeType | null {
  if (!cls) return null;
  const upper = cls.toUpperCase();
  return (Object.values(NodeType) as string[]).includes(upper) ? (upper as NodeType) : null;
}

/** Split a line on `;`, but not inside a quoted label or an entity such as `#quot;`. */
function splitStatements(line: string): string[] {
  const parts: string[] = [];
  let current = '';
  let inQuote = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') inQuote = !inQuote;
    if (ch === '#') {
      const entity = /^#[A-Za-z0-9]+;/.exec(line.slice(i));
      if (entity) { current += entity[0]; i += entity[0].length - 1; continue; }
    }
    if (ch === ';' && !inQuote) { parts.push(current); current = ''; continue; }
    current += ch;
  }
  parts.push(current);
  return parts;
}

export function mermaidToWorkflow(source: string, fallbackName = 'Imported from Mermaid'): MermaidImportResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const fail = (msg: string): MermaidImportResult => ({ errors: [...errors, msg], warnings });

  if (source.length > MAX_MERMAID_CHARS) return fail(`The diagram is too large (max ${MAX_MERMAID_CHARS / 1000} KB).`);

  let name = fallbackName;
  let text = source.replace(/\r\n?/g, '\n');
  const front = /^\s*---\n([\s\S]*?)\n---\s*\n/.exec(text);
  if (front) {
    const title = /^title:\s*(.+)$/m.exec(front[1]);
    if (title) name = title[1].trim().replace(/^["']|["']$/g, '');
    text = text.slice(front[0].length);
  }

  const drafts = new Map<string, DraftNode>();
  const edges: WorkflowEdge[] = [];
  const classAssignments: { ids: string[]; cls: string }[] = [];
  let sawHeader = false;
  let sawSubgraph = false;

  const declare = (p: ParsedNode) => {
    let d = drafts.get(p.id);
    if (!d) {
      d = { id: p.id, name: p.id, type: NodeType.TRANSFORM, guessed: true };
      drafts.set(p.id, d);
    }
    if (p.label !== undefined && p.label !== '') d.name = p.label;
    const explicit = typeFromClass(p.cls);
    if (explicit) {
      d.type = explicit; d.guessed = false;
    } else if (p.shape) {
      const byShape = SHAPE_TYPE[p.shape];
      const label = p.label ?? '';
      if (byShape) { d.type = byShape; d.guessed = false; }
      else if ((p.shape === 'stadium' || p.shape === 'circle' || p.shape === 'round') && START_LABEL.test(label)) { d.type = NodeType.START; d.guessed = false; }
      else if ((p.shape === 'stadium' || p.shape === 'circle' || p.shape === 'round') && END_LABEL.test(label)) { d.type = NodeType.END; d.guessed = false; }
      else if (p.shape === 'circle') { d.type = NodeType.HITL; d.guessed = false; }
      else if (d.guessed) { d.type = NodeType.TRANSFORM; d.guessed = true; }
    }
  };

  const statements = text.split('\n').flatMap((line, i) => {
    const noComment = line.replace(/%%.*$/, '').trim();
    return noComment ? splitStatements(noComment).map((s) => ({ line: i + 1, text: s.trim() })).filter((s) => s.text) : [];
  });

  const nameComment = /^\s*%%\s*AiFlow workflow:\s*(.+)$/m.exec(text);
  if (nameComment) name = nameComment[1].trim();

  for (const stmt of statements) {
    const s = stmt.text;
    if (!sawHeader) {
      if (!/^(flowchart|graph)\b/i.test(s)) {
        return fail('This does not look like a Mermaid flowchart: the first line must start with "flowchart" or "graph" (for example "flowchart TD").');
      }
      sawHeader = true;
      const rest = s.replace(/^(flowchart|graph)\s*(TD|TB|BT|LR|RL)?/i, '').trim();
      if (!rest) continue;
      // a statement on the header line: fall through and parse the remainder
      stmtParse(rest, stmt.line);
      continue;
    }
    stmtParse(s, stmt.line);
  }

  function stmtParse(s: string, line: number) {
    if (IGNORED_LINE.test(s)) return;
    if (/^subgraph\b/i.test(s) || /^end$/i.test(s)) { sawSubgraph = true; return; }
    const cls = /^class\s+([^\s]+)\s+([A-Za-z0-9_-]+)$/i.exec(s);
    if (cls) { classAssignments.push({ ids: cls[1].split(','), cls: cls[2] }); return; }
    try {
      const sc = new Scanner(s);
      let left = parseNodeGroup(sc);
      left.forEach(declare);
      while (!sc.done()) {
        const link = parseLink(sc);
        if (!link) throw new Error(`Unsupported syntax near "${sc.rest().slice(0, 20)}".`);
        const right = parseNodeGroup(sc);
        right.forEach(declare);
        for (const a of left) for (const b of right) {
          const dup = edges.some((e) => e.source === a.id && e.target === b.id && e.condition === link.label);
          if (!dup) edges.push({ source: a.id, target: b.id, ...(link.label ? { condition: link.label } : {}) });
        }
        left = right;
      }
    } catch (err) {
      errors.push(`Line ${line}: ${err instanceof Error ? err.message : 'could not be read.'}`);
    }
  }

  if (!sawHeader) return fail('The diagram is empty.');
  if (errors.length) return { errors, warnings };

  for (const { ids, cls } of classAssignments) {
    const type = typeFromClass(cls);
    if (!type) continue;
    for (const id of ids) {
      const d = drafts.get(id.trim());
      if (d) { d.type = type; d.guessed = false; }
    }
  }

  if (sawSubgraph) warnings.push('Subgraphs are not supported; their nodes were imported without grouping.');
  if (drafts.size === 0) return fail('The diagram has no nodes.');
  if (drafts.size > MAX_NODES) return fail(`The diagram has ${drafts.size} nodes; the limit is ${MAX_NODES}.`);
  if (edges.length > MAX_EDGES) return fail(`The diagram has ${edges.length} edges; the limit is ${MAX_EDGES}.`);

  // ── Make sure there is exactly one START and at least one END ──
  const nodes = [...drafts.values()];
  const hasIncoming = (id: string) => edges.some((e) => e.target === id);
  const hasOutgoing = (id: string) => edges.some((e) => e.source === id);

  const starts = nodes.filter((n) => n.type === NodeType.START);
  if (starts.length > 1) return fail(`The diagram has ${starts.length} START nodes (${starts.map((s) => s.name).join(', ')}); a workflow needs exactly one.`);
  if (starts.length === 0) {
    const roots = nodes.filter((n) => !hasIncoming(n.id));
    const guessedRoots = roots.filter((n) => n.guessed);
    if (roots.length === 1 && guessedRoots.length === 1) {
      guessedRoots[0].type = NodeType.START;
      guessedRoots[0].guessed = false;
      warnings.push(`"${guessedRoots[0].name}" has no incoming edges, so it was used as the START node.`);
    } else {
      let id = 'start';
      for (let i = 2; drafts.has(id); i++) id = `start_${i}`;
      nodes.unshift({ id, name: 'Start', type: NodeType.START, guessed: false });
      for (const r of roots) edges.push({ source: id, target: r.id });
      warnings.push('The diagram has no START node, so one was added in front of the nodes that have no incoming edges.');
    }
  }

  const ends = nodes.filter((n) => n.type === NodeType.END);
  if (ends.length === 0) {
    const leaves = nodes.filter((n) => n.type !== NodeType.START && !hasOutgoing(n.id));
    const guessedLeaves = leaves.filter((n) => n.guessed);
    if (leaves.length > 0 && guessedLeaves.length === leaves.length) {
      for (const l of leaves) { l.type = NodeType.END; l.guessed = false; }
      warnings.push(`${leaves.length === 1 ? `"${leaves[0].name}" has` : 'Nodes without outgoing edges have'} no outgoing edges, so ${leaves.length === 1 ? 'it was' : 'they were'} used as END.`);
    } else {
      let id = 'end_node';
      for (let i = 2; drafts.has(id); i++) id = `end_node_${i}`;
      nodes.push({ id, name: 'End', type: NodeType.END, guessed: false });
      for (const l of (leaves.length ? leaves : nodes.filter((n) => n.type !== NodeType.START && n.id !== id))) {
        edges.push({ source: l.id, target: id });
      }
      warnings.push('The diagram has no END node, so one was added after the nodes that have no outgoing edges.');
    }
  }

  const guessed = nodes.filter((n) => n.guessed).map((n) => n.name);
  if (guessed.length > 0) {
    warnings.push(`Node type could not be told from the diagram for: ${guessed.slice(0, 5).join(', ')}${guessed.length > 5 ? '…' : ''}. They were imported as TRANSFORM; change them in the properties panel.`);
  }
  warnings.push('Mermaid does not carry node settings (prompts, URLs, expressions). Fill them in after importing, then run Validate.');

  const workflowNodes: WorkflowNode[] = nodes.map((n) => ({
    id: n.id, type: n.type, name: n.name, position: { x: 0, y: 0 }, config: {},
  }));
  const workflow: Workflow = autoLayoutWorkflow({
    version: '1.0',
    id: crypto.randomUUID(),
    name,
    description: '',
    nodes: workflowNodes,
    edges,
    metadata: {},
  });
  return { workflow, errors, warnings };
}
