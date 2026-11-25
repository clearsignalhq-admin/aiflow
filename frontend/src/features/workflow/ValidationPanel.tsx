import { HelpIcon } from '../../components/HelpIcon';
import type { LintResult } from '../../models/lint';
import { summariseEstimates } from './lintUtils';

interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

interface Props {
  result: ValidationResult;
  lint?: LintResult | null;
  onSelectNode?: (nodeId: string) => void;
  onDismiss: () => void;
}

const SEVERITY_ICON = { error: '✗', warning: '⚠', info: 'ⓘ' } as const;

export function ValidationPanel({ result, lint, onSelectNode, onDismiss }: Props) {
  const { valid, errors, warnings } = result;

  return (
    <div className={`validation-panel ${valid ? 'validation-panel--valid' : 'validation-panel--invalid'}`}>
      <div className="validation-panel-header">
        <span className="validation-panel-title">
          {valid ? '✓ Workflow valid' : `✗ ${errors.length} error${errors.length !== 1 ? 's' : ''}`}
          {warnings.length > 0 && (
            <span className="validation-warning-count">
              {' '}· {warnings.length} warning{warnings.length !== 1 ? 's' : ''}
            </span>
          )}
          <HelpIcon
            title="Workflow Validation"
              guide="checking-your-design"
            body="Checks the workflow structure for problems.\n\nErrors must be fixed before the workflow will simulate or export reliably. Common errors: missing START or END node, disconnected nodes, invalid edge references.\n\nWarnings are advisory — the workflow can still run, but something may behave unexpectedly."
          />
        </span>
        <button className="validation-dismiss" onClick={onDismiss} title="Dismiss">✕</button>
      </div>

      {errors.length > 0 && (
        <ul className="validation-list validation-list--errors">
          {errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}

      {warnings.length > 0 && (
        <ul className="validation-list validation-list--warnings">
          {warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}

      {lint && lint.findings.length > 0 && (
        <div className="validation-lint">
          <div className="validation-lint-title">
            Design findings ({lint.findings.length})
            <HelpIcon
              title="Design Findings"
              guide="checking-your-design"
              body="Deterministic checks that go beyond structure: unreachable nodes, dead ends, decisions without two branches, API/database calls with no failure branch, human review placed after an irreversible step, fields that nothing upstream produces, and cycles.\n\nClick a finding to select the node. A badge on the node shows how many findings it has."
            />
          </div>
          <ul className="validation-list validation-lint-list">
            {lint.findings.map((f, i) => (
              <li key={i} className={`validation-lint-item validation-lint-item--${f.severity}`}>
                <button
                  className="validation-lint-button"
                  disabled={!f.node_id || !onSelectNode}
                  onClick={() => f.node_id && onSelectNode?.(f.node_id)}
                  title={f.node_id ? 'Select this node' : undefined}
                >
                  <span className="validation-lint-icon">{SEVERITY_ICON[f.severity]}</span>
                  <span>
                    {f.message}
                    {f.fix_hint && <span className="validation-lint-hint"> — {f.fix_hint}</span>}
                    <span className="validation-lint-rule"> [{f.rule_id}]</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {lint && summariseEstimates(lint.estimates) && (
        <div className="validation-estimate">{summariseEstimates(lint.estimates)}</div>
      )}
    </div>
  );
}

export type { ValidationResult };
