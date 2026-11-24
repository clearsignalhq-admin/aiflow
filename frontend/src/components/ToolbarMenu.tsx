import { useEffect, useRef } from 'react';
import type { ActionItem } from './actions';
import { isEnabled } from './actions';

interface Props {
  label: string;
  items: ActionItem[];
  open: boolean;
  onToggle: () => void;
  /** Called when the pointer enters while another menu is open, so moving along the bar switches menus. */
  onHover: () => void;
  onClose: () => void;
}

/** A dropdown button with keyboard support: Enter/Space/↓ opens, ↑/↓ move, Enter picks, Esc closes. */
export function ToolbarMenu({ label, items, open, onToggle, onHover, onClose }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Focus the first available item when the menu opens.
  useEffect(() => {
    if (!open) return;
    rootRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) onClose();
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open, onClose]);

  const move = (delta: number) => {
    const els = Array.from(rootRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? []);
    if (els.length === 0) return;
    const at = els.indexOf(document.activeElement as HTMLButtonElement);
    els[(at + delta + els.length) % els.length].focus();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape' && open) {
      e.preventDefault();
      e.stopPropagation();
      onClose();
      buttonRef.current?.focus();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (!open) onToggle(); else move(1);
    } else if (e.key === 'ArrowUp' && open) {
      e.preventDefault();
      move(-1);
    } else if (e.key === 'Tab' && open) {
      onClose();
    }
  };

  // Items are grouped visually when an id starts with a new "section:" prefix.
  const sectionOf = (item: ActionItem) => (item.id.includes(':') ? item.id.split(':')[0] : '');
  return (
    <div className="tb-menu" ref={rootRef} onKeyDown={onKeyDown} onMouseEnter={onHover}>
      <button
        ref={buttonRef}
        className={`btn btn-ghost tb-menu-btn${open ? ' tb-menu-btn--open' : ''}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={onToggle}
      >
        {label} <span className="tb-caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="tb-menu-list" role="menu" aria-label={label}>
          {items.map((item, i) => {
            const divider = i > 0 && sectionOf(items[i - 1]) !== '' && sectionOf(item) !== sectionOf(items[i - 1]);
            return (
              <div key={item.id}>
                {divider && <div className="tb-menu-divider" role="separator" />}
                <button
                  role="menuitem"
                  className="tb-menu-item"
                  disabled={!isEnabled(item)}
                  title={!isEnabled(item) ? item.disabledReason : item.hint}
                  onClick={() => { onClose(); item.onSelect?.(); }}
                >
                  <span className="tb-menu-item-label">{item.label}</span>
                  {item.shortcut && <kbd className="tb-kbd">{item.shortcut}</kbd>}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
