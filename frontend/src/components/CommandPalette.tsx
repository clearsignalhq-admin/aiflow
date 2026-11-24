import { useEffect, useMemo, useRef, useState } from 'react';
import type { ActionItem } from './actions';
import { filterActions, isEnabled } from './actions';

interface Props {
  actions: ActionItem[];
  onClose: () => void;
}

/** Search every action by name; ↑/↓ to move, Enter to run, Esc to close. */
export function CommandPalette({ actions, onClose }: Props) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const results = useMemo(() => filterActions(actions, query), [actions, query]);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const run = (a: ActionItem | undefined) => {
    if (!a || !isEnabled(a)) return;
    onClose();
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
                <span className="cp-item-group">{a.group}</span>
                {a.shortcut && <kbd className="tb-kbd">{a.shortcut}</kbd>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
