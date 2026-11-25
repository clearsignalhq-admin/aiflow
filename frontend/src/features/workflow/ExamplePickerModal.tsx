import { useState, useMemo } from 'react';
import type { Workflow } from '../../models/workflow';
import { deserializeWorkflow } from '../../utils/workflowSerializer';
import { HelpIcon } from '../../components/HelpIcon';

import { CATALOG } from './exampleCatalog';
import type { ExampleEntry } from './exampleCatalog';

const SECTIONS: { key: 'easy' | 'medium' | 'complex'; label: string; subtitle: string }[] = [
  { key: 'easy',    label: 'Easy',    subtitle: 'short flows · a few steps' },
  { key: 'medium',  label: 'Medium',  subtitle: 'branching · human review · failure handling' },
  { key: 'complex', label: 'Complex', subtitle: 'multi-branch pipelines' },
];

const DIFFICULTY_COLOR: Record<string, string> = {
  easy:    '#4ade80',
  medium:  '#fbbf24',
  complex: '#f87171',
};

interface Props {
  onClose: () => void;
  onSelect: (workflow: Workflow) => void;
}

function entryName(entry: ExampleEntry): string {
  return (entry.json as { name: string }).name;
}

function entryDescription(entry: ExampleEntry): string {
  return (entry.json as { description: string }).description;
}

export function ExamplePickerModal({ onClose, onSelect }: Props) {
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    if (!q) return CATALOG;
    return CATALOG.filter((e) =>
      entryName(e).toLowerCase().includes(q) ||
      e.industry.toLowerCase().includes(q) ||
      entryDescription(e).toLowerCase().includes(q) ||
      e.tags.some((t) => t.includes(q)),
    );
  }, [query]);

  const handleSelect = (entry: ExampleEntry) => {
    const workflow = deserializeWorkflow(JSON.stringify(entry.json));
    onSelect(workflow);
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal example-picker-modal">
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span className="modal-title">Example Workflows</span>
            <HelpIcon
              title="Example Workflows"
              guide="starting-a-workflow"
              body="Pre-built workflows ready to explore and simulate. Grouped by difficulty:\n\nEasy — short flows with a few steps.\nMedium — branching, human review and failure handling.\nComplex — multi-branch pipelines.\n\nMost examples handle failures and keep a person in the loop before anything is changed, so they are good patterns to copy. Supply Chain Monitor is the exception on purpose: try Validate, Suggest changes and Safety checks on it.\n\nClick any card to load the workflow onto the canvas. Search by name, industry, or tag."
            />
          </div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="example-picker-search-row">
          <input
            className="example-picker-search"
            placeholder="Search by name, industry, or tag…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
        </div>

        <div className="example-picker-body">
          {SECTIONS.map((section) => {
            const entries = filtered.filter((e) => e.difficulty === section.key);
            if (entries.length === 0) return null;
            return (
              <div key={section.key} className="example-section">
                <div className="example-section-header">
                  <span
                    className="example-difficulty-badge"
                    style={{ background: DIFFICULTY_COLOR[section.key] }}
                  >
                    {section.label}
                  </span>
                  <span className="example-section-subtitle">{section.subtitle}</span>
                </div>
                <div className="example-cards">
                  {entries.map((entry) => (
                    <button
                      key={(entry.json as { id: string }).id}
                      className="example-card"
                      onClick={() => handleSelect(entry)}
                    >
                      <div className="example-card-top">
                        <span className="example-card-name">{entryName(entry)}</span>
                        <span className="example-card-nodes">{entry.nodeCount} nodes</span>
                      </div>
                      <div className="example-card-industry">{entry.industry}</div>
                      <div className="example-card-desc">{entryDescription(entry)}</div>
                      <div className="example-card-tags">
                        {entry.tags.map((t) => (
                          <span key={t} className="example-tag">{t}</span>
                        ))}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}

          {filtered.length === 0 && (
            <div className="example-picker-empty">No examples match "{query}"</div>
          )}
        </div>
      </div>
    </div>
  );
}
