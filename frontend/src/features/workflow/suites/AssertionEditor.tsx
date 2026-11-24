import { ASSERTION_TYPES, COMPARE_OPS } from '../../../models/suites';
import type { Assertion, AssertionType } from '../../../models/suites';
import { JsonField } from '../JsonField';
import {
  ASSERTION_LABELS, assertionProblem, changeAssertionType, formatLooseValue, parseLooseValue,
} from './assertionUtils';

interface Props {
  assertion: Assertion;
  nodes: { id: string; name: string }[];
  onChange: (next: Assertion) => void;
  onRemove: () => void;
}

const HAS_PATH: AssertionType[] = ['equals', 'contains', 'exists', 'compare', 'one_of', 'matches_schema'];

function valuesToText(values: unknown[] | undefined): string {
  return values && values.length ? values.map(formatLooseValue).join(', ') : '';
}

function textToValues(text: string): unknown[] {
  return text.split(',').map((t) => t.trim()).filter((t) => t !== '').map(parseLooseValue);
}

export function AssertionEditor({ assertion: a, nodes, onChange, onRemove }: Props) {
  const set = (patch: Partial<Assertion>) => onChange({ ...a, ...patch });
  const problem = assertionProblem(a);

  return (
    <div className="assertion-row" data-testid="assertion-row">
      <div className="assertion-line">
        <select
          className="prop-input prop-select assertion-type"
          aria-label="Assertion type"
          value={a.type}
          onChange={(e) => onChange(changeAssertionType(a, e.target.value as AssertionType))}
        >
          {ASSERTION_TYPES.map((t) => <option key={t} value={t}>{ASSERTION_LABELS[t]}</option>)}
        </select>

        {HAS_PATH.includes(a.type) && (
          <input
            className="prop-input assertion-path"
            aria-label="Output path"
            placeholder={a.type === 'exists' || a.type === 'compare' ? 'field.path' : 'field.path (empty = whole output)'}
            value={a.path ?? ''}
            onChange={(e) => set({ path: e.target.value })}
          />
        )}

        {(a.type === 'equals' || a.type === 'contains') && (
          <input
            className="prop-input assertion-value"
            aria-label="Expected value"
            placeholder='value, e.g. premium, 42, true or "42"'
            value={formatLooseValue(a.value)}
            onChange={(e) => set({ value: parseLooseValue(e.target.value) })}
          />
        )}

        {a.type === 'exists' && (
          <label className="assertion-check">
            <input
              type="checkbox"
              aria-label="Must exist"
              checked={a.value !== false}
              onChange={(e) => set({ value: e.target.checked })}
            />
            must exist
          </label>
        )}

        {a.type === 'compare' && (
          <>
            <select
              className="prop-input prop-select assertion-op"
              aria-label="Comparison"
              value={a.op ?? '>='}
              onChange={(e) => set({ op: e.target.value })}
            >
              {COMPARE_OPS.map((op) => <option key={op} value={op}>{op}</option>)}
            </select>
            <input
              className="prop-input assertion-number"
              type="number"
              aria-label="Compare with"
              value={typeof a.value === 'number' ? a.value : ''}
              onChange={(e) => set({ value: e.target.value === '' ? undefined : Number(e.target.value) })}
            />
          </>
        )}

        {a.type === 'one_of' && (
          <input
            className="prop-input assertion-value"
            aria-label="Allowed values"
            placeholder="comma-separated, e.g. basic, premium"
            value={valuesToText(a.values)}
            onChange={(e) => set({ values: textToValues(e.target.value) })}
          />
        )}

        {a.type === 'expression' && (
          <input
            className="prop-input assertion-value"
            aria-label="Expression"
            placeholder='e.g. output.total > 100 and "refund" in visited'
            value={a.expression ?? ''}
            onChange={(e) => set({ expression: e.target.value })}
          />
        )}

        {(a.type === 'visits_node' || a.type === 'skips_node') && (
          <select
            className="prop-input prop-select assertion-value"
            aria-label="Node"
            value={a.node_id ?? ''}
            onChange={(e) => set({ node_id: e.target.value })}
          >
            <option value="">Choose a node…</option>
            {nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
          </select>
        )}

        {a.type === 'max_steps' && (
          <input
            className="prop-input assertion-number"
            type="number"
            min={1}
            aria-label="Maximum steps"
            value={a.max_steps ?? ''}
            onChange={(e) => set({ max_steps: e.target.value === '' ? undefined : Number(e.target.value) })}
          />
        )}

        <button className="btn btn-ghost assertion-remove" onClick={onRemove} aria-label="Remove assertion" title="Remove assertion">✕</button>
      </div>

      {a.type === 'matches_schema' && (
        <JsonField
          value={a.output_schema}
          ariaLabel="Output schema"
          placeholder='{ "type": "object", "required": ["id"] }'
          onCommit={(v) => set({ output_schema: v })}
        />
      )}

      <div className="assertion-line assertion-meta">
        <input
          className="prop-input assertion-label"
          aria-label="Assertion label"
          placeholder="Label (optional)"
          value={a.label ?? ''}
          onChange={(e) => set({ label: e.target.value || undefined })}
        />
        {problem && <span className="assertion-problem" role="alert">{problem}</span>}
      </div>
    </div>
  );
}
