import { useState } from 'react';
import type { Assertion, AssertionType, SuiteCase } from '../../../models/suites';
import { ASSERTION_TYPES } from '../../../models/suites';
import { JsonField } from '../JsonField';
import { AssertionEditor } from './AssertionEditor';
import { ASSERTION_LABELS, blankCase, caseProblem, newAssertion } from './assertionUtils';
import { newKey } from './draftUtils';
import type { DraftCase } from './draftUtils';

interface Props {
  cases: DraftCase[];
  nodes: { id: string; name: string }[];
  maxCases: number;
  sampleInput?: Record<string, unknown>;
  disabled?: boolean;
  onChange: (next: DraftCase[]) => void;
}

export function SuiteCasesEditor({ cases, nodes, maxCases, sampleInput, disabled, onChange }: Props) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(cases.slice(0, 1).map((c) => c.key)));
  const [newType, setNewType] = useState<AssertionType>('equals');

  const update = (key: string, patch: Partial<SuiteCase>) =>
    onChange(cases.map((c) => (c.key === key ? { ...c, data: { ...c.data, ...patch } } : c)));

  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });

  const addCase = (withSample: boolean) => {
    const key = newKey();
    onChange([...cases, { key, data: blankCase(cases.length + 1, withSample ? sampleInput : undefined) }]);
    setOpen((prev) => new Set(prev).add(key));
  };

  const setAssertions = (key: string, assertions: Assertion[]) => update(key, { assertions });

  const atLimit = cases.length >= maxCases;

  return (
    <div className="suite-cases">
      {cases.length === 0 && <div className="run-history-empty">No test cases yet. Add one below.</div>}

      {cases.map((c, index) => {
        const isOpen = open.has(c.key);
        const problem = caseProblem(c.data);
        return (
          <div key={c.key} className={`suite-case${problem ? ' suite-case--invalid' : ''}`} data-testid="suite-case">
            <div className="suite-case-header">
              <button className="btn btn-ghost suite-case-toggle" onClick={() => toggle(c.key)} aria-expanded={isOpen} aria-label={isOpen ? 'Collapse case' : 'Expand case'}>
                {isOpen ? '▾' : '▸'}
              </button>
              <input
                className="prop-input suite-case-name"
                aria-label={`Case ${index + 1} name`}
                value={c.data.name}
                disabled={disabled}
                onChange={(e) => update(c.key, { name: e.target.value })}
              />
              <span className="suite-case-count">{c.data.assertions.length} check{c.data.assertions.length === 1 ? '' : 's'}</span>
              <button
                className="btn btn-ghost"
                disabled={disabled}
                aria-label={`Remove case ${index + 1}`}
                onClick={() => onChange(cases.filter((x) => x.key !== c.key))}
              >
                Remove
              </button>
            </div>

            {isOpen && (
              <div className="suite-case-body">
                {problem && <div className="assertion-problem" role="alert">{problem}</div>}

                <label className="prop-label">Input</label>
                <JsonField
                  value={c.data.input}
                  ariaLabel={`Case ${index + 1} input`}
                  placeholder='{ "message": "I want a refund" }'
                  onCommit={(v) => update(c.key, { input: v ?? {} })}
                />

                <label className="prop-label">
                  Checks
                  <span className="suite-hint"> — evaluated against the final output of the workflow</span>
                </label>
                {c.data.assertions.map((a, i) => (
                  <AssertionEditor
                    key={i}
                    assertion={a}
                    nodes={nodes}
                    onChange={(next) => setAssertions(c.key, c.data.assertions.map((x, j) => (j === i ? next : x)))}
                    onRemove={() => setAssertions(c.key, c.data.assertions.filter((_, j) => j !== i))}
                  />
                ))}
                <div className="assertion-add">
                  <select
                    className="prop-input prop-select"
                    aria-label="New check type"
                    value={newType}
                    onChange={(e) => setNewType(e.target.value as AssertionType)}
                  >
                    {ASSERTION_TYPES.map((t) => <option key={t} value={t}>{ASSERTION_LABELS[t]}</option>)}
                  </select>
                  <button
                    className="btn btn-ghost"
                    disabled={disabled || c.data.assertions.length >= 20}
                    onClick={() => setAssertions(c.key, [...c.data.assertions, newAssertion(newType)])}
                  >
                    + Add check
                  </button>
                </div>

                <div className="suite-seed">
                  <label className="prop-label" htmlFor={`seed-${c.key}`}>Seed (optional)</label>
                  <input
                    id={`seed-${c.key}`}
                    className="prop-input assertion-number"
                    type="number"
                    min={0}
                    placeholder="auto"
                    value={c.data.seed ?? ''}
                    onChange={(e) => update(c.key, { seed: e.target.value === '' ? null : Math.max(0, Math.floor(Number(e.target.value))) })}
                  />
                  <span className="suite-hint">Pins the mock data and branch this case takes.</span>
                </div>
              </div>
            )}
          </div>
        );
      })}

      <div className="suite-add-row">
        <button className="btn btn-primary" disabled={disabled || atLimit} onClick={() => addCase(false)}>+ Add case</button>
        {sampleInput && Object.keys(sampleInput).length > 0 && (
          <button className="btn btn-ghost" disabled={disabled || atLimit} onClick={() => addCase(true)}>
            + Add case from sample input
          </button>
        )}
        <span className="suite-hint">{cases.length} / {maxCases} cases</span>
      </div>
    </div>
  );
}
