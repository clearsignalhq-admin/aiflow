import { useEffect, useMemo, useRef, useState } from 'react';
import type { ActionItem } from './actions';
import { filterActions, isEnabled } from './actions';

interface Props {
  actions: ActionItem[];
  /** Ids of recently used actions, newest first; shown first (labelled Recent) until something is typed. */
  recentIds?: string[];
  onPick?: (action: ActionItem) => void;
  onClose: () => void;
}

/** Search every action by name; ↑/↓ to move, Enter to run, Esc to close. */
export function CommandPalette({ actions, recentIds = [], onPick, onClose }: Props) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const recent = useMemo(
    () => recentIds.map((id) => actions.find((a) => a.id === id)).filter((a): a is ActionItem => !!a && isEnabled(a)),
    [actions, recentIds],
  );
  const recentSet = useMemo(() => new Set(recent.map((a) => a.id)), [recent]);
  const typing = query.trim().length > 0;
  const results = useMemo(
    () => (typing ? filterActions(actions, query) : [...recent, ...actions.filter((a) => !recentSet.has(a.id))]),
    [actions, query, typing, recent, recentSet],
  );

  useEffect(() => { inputRef.current?.focus(); }, []);

  const run = (a: ActionItem | undefined) => {
    if (!a || !isEnabled(a)) return;
    onClose();
    onPick?.(a);
    a.onSelect?.();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); onClose(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => Math.min(i + 1, results.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); run(results[active]); }
  };

  return (
    <div className="modal-overlay cp-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="cp" role="dialog" aria-label="Command palette" onKeyDown={onKeyDown}>
        <input
          ref={inputRef}
          className="cp-input"
          role="combobox"
          aria-expanded="true"
          aria-controls="cp-list"
          aria-label="Search actions"
          placeholder="Search actions…  (for example: validate, share, export)"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setActive(0); }}
        />
        <ul className="cp-list" id="cp-list" role="listbox">
          {results.length === 0 && <li className="cp-empty">No action matches “{query}”.</li>}
          {results.map((a, i) => (
            <li key={a.id} role="option" aria-selected={i === active} aria-disabled={!isEnabled(a)}>
              <button
                className={`cp-item${i === active ? ' cp-item--active' : ''}`}
                disabled={!isEnabled(a)}
                onMouseMove={() => setActive(i)}
                onClick={() => run(a)}
                title={!isEnabled(a) ? a.disabledReason : undefined}
              >
                <span className="cp-item-main">
                  <span className="cp-item-label">{a.label}</span>
                  {(a.hint || (!isEnabled(a) && a.disabledReason)) && (
                    <span className="cp-item-hint">{!isEnabled(a) && a.disabledReason ? a.disabledReason : a.hint}</span>
                  )}
                </span>
                <span className="cp-item-group">{!typing && recentSet.has(a.id) ? 'Recent' : a.group}</span>
                {a.shortcut && <kbd className="tb-kbd">{a.shortcut}</kbd>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
