import type { Workflow, WorkflowEdge } from '../../models/workflow';
import { getNodeDefinition } from './nodes/nodeDefinitions';
import type { ConfigField } from './nodes/nodeDefinitions';
import { HelpIcon } from '../../components/HelpIcon';
import { JsonField } from './JsonField';
import { NodeType } from '../../models/workflow';

interface Props {
  workflow: Workflow;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  onNameChange: (nodeId: string, name: string) => void;
  onConfigChange: (nodeId: string, key: string, value: unknown) => void;
  onSchemaChange?: (nodeId: string, key: 'input_schema' | 'output_schema', value: Record<string, unknown> | undefined) => void;
  onEdgeChange: (source: string, target: string, updates: { condition?: string; notes?: string }) => void;
}

export function PropertiesPanel({ workflow, selectedNodeId, selectedEdgeId, onNameChange, onConfigChange, onSchemaChange, onEdgeChange }: Props) {
  const node = selectedNodeId ? workflow.nodes.find((n) => n.id === selectedNodeId) : null;

  // Resolve selected edge from domain model using the stable RF edge ID format
  const edge: WorkflowEdge | null = selectedEdgeId
    ? workflow.edges.find((e) => `${e.source}→${e.target}` === selectedEdgeId) ?? null
    : null;

  if (!node && edge) {
    const sourceNode = workflow.nodes.find((n) => n.id === edge.source);
    const targetNode = workflow.nodes.find((n) => n.id === edge.target);
    return (
      <aside className="properties-panel">
        <div className="properties-title">
          Edge
          <HelpIcon
            title="Edge Properties"
            body="Condition label: the routing key used by Condition nodes. The simulation engine matches this label against the result of the CONDITION node's expression to decide which branch to follow (true/yes or false/no for comparisons; otherwise the returned text, e.g. complex; else is the fallback).\n\nNotes: a free-text annotation for documentation purposes — not used during simulation."
          />
        </div>
        <div className="prop-group">
          <label className="prop-label">From → To</label>
          <div className="prop-edge-route">
            {sourceNode?.name ?? edge.source} → {targetNode?.name ?? edge.target}
          </div>
        </div>
        <div className="prop-group">
          <label className="prop-label" style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            Condition label
            <HelpIcon
              title="Condition Label"
              body={'Set this on edges that leave a Condition node. The simulator matches the node\'s expression result against these labels (case-insensitive). A comparison such as input.amount > 5000 routes to the edge labelled true/yes or false/no. An expression that returns text, such as "complex" if input.x > 1 else "simple", routes to the edge with that label. An edge labelled else is used when nothing else matches.\n\nLeave blank on non-conditional edges.'}
            />
          </label>
          <input
            className="prop-input"
            value={edge.condition ?? ''}
            placeholder="e.g. true, complex, approved"
            onChange={(e) => onEdgeChange(edge.source, edge.target, { condition: e.target.value || undefined })}
          />
        </div>
        <div className="prop-group">
          <label className="prop-label">Notes</label>
          <textarea
            className="prop-input prop-textarea"
            value={edge.notes ?? ''}
            placeholder="Optional annotation…"
            onChange={(e) => onEdgeChange(edge.source, edge.target, { notes: e.target.value || undefined })}
          />
        </div>
      </aside>
    );
  }

  if (!node) {
    return (
      <aside className="properties-panel">
        <div className="properties-empty">Select a node or edge to edit its properties.</div>
      </aside>
    );
  }

  const def = getNodeDefinition(node.type);

  return (
    <aside className="properties-panel">
      <div className="properties-title">
        Properties
        <HelpIcon
          title="Properties Panel"
          body="Shows the configuration for the selected node. Click any node on the canvas to select it.\n\nChange the node's name and configure its behaviour. Each node type exposes different fields — for example, LLM nodes have a prompt and temperature, API nodes have a URL and method."
        />
      </div>

      <div className="prop-group">
        <label className="prop-label">Name</label>
        <input
          className="prop-input"
          value={node.name}
          onChange={(e) => onNameChange(node.id, e.target.value)}
        />
      </div>

      <div className="prop-group">
        <label className="prop-label">Type</label>
        <div className="prop-badge" style={{ background: def.color }}>
          {node.type}
        </div>
      </div>

      {def.configFields.length > 0 && (
        <>
          <div className="properties-section-title">Configuration</div>
          {def.configFields.map((field: ConfigField) => (
            <div key={field.key} className="prop-group">
              <label className="prop-label">{field.label}</label>
              <ConfigFieldInput
                field={field}
                value={(node.config as Record<string, unknown>)[field.key]}
                onChange={(val) => onConfigChange(node.id, field.key, val)}
              />
            </div>
          ))}
        </>
      )}

      {onSchemaChange && node.type !== NodeType.START && node.type !== NodeType.END && node.type !== NodeType.CONDITION && (
        <>
          <div className="properties-section-title">
            Data contract
            <HelpIcon
              title="Data Contract"
              body="Optional JSON Schemas describing the data this node receives and produces, e.g. {&quot;type&quot;: &quot;object&quot;, &quot;properties&quot;: {&quot;tier&quot;: {&quot;type&quot;: &quot;string&quot;, &quot;enum&quot;: [&quot;basic&quot;, &quot;premium&quot;]}}}.\n\nValidate checks that connected nodes agree. During simulation, a node with an output schema produces mock data that matches it (reproducible per seed), so Condition expressions take real branches.\n\nSupported keywords: type, properties, required, items, enum, const, default, example, minimum, maximum, minItems, maxItems."
            />
          </div>
          <div className="prop-group">
            <label className="prop-label">Input schema</label>
            <JsonField
              key={`${node.id}-in`}
              value={node.input_schema}
              placeholder='{ "type": "object", "properties": { } }'
              ariaLabel="Input schema"
              onCommit={(v) => onSchemaChange(node.id, 'input_schema', v)}
            />
          </div>
          <div className="prop-group">
            <label className="prop-label">Output schema</label>
            <JsonField
              key={`${node.id}-out`}
              value={node.output_schema}
              placeholder='{ "type": "object", "properties": { } }'
              ariaLabel="Output schema"
              onCommit={(v) => onSchemaChange(node.id, 'output_schema', v)}
            />
          </div>
          {node.type !== NodeType.HITL && (
            <div className="prop-group">
              <label className="prop-label">
                Mock output (pinned)
                <HelpIcon
                  title="Pinned Mock Output"
                  body="A fixed output used by the simulator for this node instead of generated data. It takes priority over the output schema. Leave empty to use the schema or the default mock. Ignored when the LLM runs in real mode."
                />
              </label>
              <JsonField
                key={`${node.id}-mock`}
                value={(node.config as Record<string, unknown>).mock_output as Record<string, unknown> | undefined}
                placeholder='{ "tier": "premium" }'
                ariaLabel="Mock output"
                onCommit={(v) => onConfigChange(node.id, 'mock_output', v)}
              />
            </div>
          )}
        </>
      )}
    </aside>
  );
}

function ConfigFieldInput({
  field,
  value,
  onChange,
}: {
  field: ConfigField;
  value: unknown;
  onChange: (val: unknown) => void;
}) {
  const strVal = value === undefined || value === null ? '' : String(value);

  if (field.type === 'textarea') {
    return (
      <textarea
        className="prop-input prop-textarea"
        value={strVal}
        placeholder={field.placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  if (field.type === 'select' && field.options) {
    return (
      <select
        className="prop-input prop-select"
        value={strVal}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Select...</option>
        {field.options.map((opt) => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
    );
  }

  if (field.type === 'number') {
    return (
      <input
        className="prop-input"
        type="number"
        value={strVal}
        placeholder={field.placeholder}
        onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
      />
    );
  }

  return (
    <input
      className="prop-input"
      type="text"
      value={strVal}
      placeholder={field.placeholder}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
