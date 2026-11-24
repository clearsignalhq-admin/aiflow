import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { Toolbar } from './Toolbar';
import { filterActions } from './actions';
import type { ActionItem } from './actions';

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: { email: 'a@b.c' }, profile: { role: 'user', name: 'Ada Lovelace' }, session: { access_token: 't' }, signOut: vi.fn() }),
}));
vi.mock('react-router-dom', () => ({ Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a> }));

const handlers = () => ({
  onNew: vi.fn(), onSave: vi.fn(), onOpen: vi.fn(), onOpenExamplePicker: vi.fn(), onValidate: vi.fn(), onGenerate: vi.fn(),
  onRefine: vi.fn(), onSimulate: vi.fn(), onEditJson: vi.fn(), onNameChange: vi.fn(), onCloud: vi.fn(), onExportCode: vi.fn(),
  onMermaid: vi.fn(), onReport: vi.fn(), onExplain: vi.fn(), onSuggest: vi.fn(), onSafety: vi.fn(), onHistory: vi.fn(), onTests: vi.fn(),
  onUndo: vi.fn(), onRedo: vi.fn(),
});
const setup = (over: Record<string, unknown> = {}) => {
  const h = handlers();
  render(<Toolbar workflowName="Flow" canRefine canUndo {...h} {...over} />);
  return h;
};
const menuButton = (name: RegExp) => screen.getByRole('button', { name });

describe('Toolbar — layout', () => {
  it('keeps the everyday actions visible and the rest inside three menus', () => {
    setup();
    for (const name of ['Validate', '▶ Simulate', 'Tests', 'Refine', 'Generate']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
    for (const name of [/^File/, /^Export/, /^Analyze/]) expect(menuButton(name)).toHaveAttribute('aria-haspopup', 'menu');
    // none of the moved actions is a top-level button any more
    for (const name of ['New', 'Open', 'Save', 'Examples', 'JSON', 'Code', 'Explain', 'Suggest', 'Safety', 'Cloud', 'Mermaid', 'History', 'Report']) {
      expect(screen.queryByRole('button', { name })).toBeNull();
    }
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('shows validation badges on the Validate button', () => {
    setup({ validationResult: { valid: false, errors: ['a', 'b'], warnings: ['w'] } });
    expect(screen.getByRole('button', { name: /Validate/ })).toHaveTextContent('2');
  });

  it('edits the workflow name', () => {
    const h = setup();
    fireEvent.change(screen.getByLabelText('Workflow name'), { target: { value: 'New name' } });
    expect(h.onNameChange).toHaveBeenCalledWith('New name');
  });
});

describe('Toolbar — menus', () => {
  it('opens a menu, runs an item and closes', () => {
    const h = setup();
    fireEvent.click(menuButton(/^File/));
    const menu = screen.getByRole('menu', { name: 'File' });
    expect(within(menu).getAllByRole('menuitem').map((i) => i.textContent)).toEqual(['New workflow', 'Open file…', 'Save to file…', 'Cloud workflows…', 'Examples…']);
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'Cloud workflows…' }));
    expect(h.onCloud).toHaveBeenCalledOnce();
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('puts every moved action in the right menu', () => {
    const h = setup();
    const pick = (menu: RegExp, item: string) => { fireEvent.click(menuButton(menu)); fireEvent.click(screen.getByRole('menuitem', { name: item })); };
    pick(/^File/, 'New workflow'); pick(/^File/, 'Open file…'); pick(/^File/, 'Save to file…'); pick(/^File/, 'Examples…');
    pick(/^Export/, 'Edit JSON'); pick(/^Export/, 'Code (Python, LangGraph, MCP)'); pick(/^Export/, 'Mermaid diagram'); pick(/^Export/, 'Report');
    pick(/^Analyze/, 'Explain'); pick(/^Analyze/, 'Suggest changes'); pick(/^Analyze/, 'Safety checks'); pick(/^Analyze/, 'Run history');
    for (const fn of [h.onNew, h.onOpen, h.onSave, h.onOpenExamplePicker, h.onEditJson, h.onExportCode, h.onMermaid, h.onReport, h.onExplain, h.onSuggest, h.onSafety, h.onHistory]) {
      expect(fn).toHaveBeenCalledOnce();
    }
  });

  it('separates groups of related items with a divider', () => {
    setup();
    fireEvent.click(menuButton(/^File/));
    expect(screen.getAllByRole('separator')).toHaveLength(1);
  });

  it('shows only one menu at a time and switches when moving along the bar', () => {
    setup();
    fireEvent.click(menuButton(/^File/));
    fireEvent.mouseEnter(menuButton(/^Export/).parentElement!);
    expect(screen.getByRole('menu', { name: 'Export' })).toBeInTheDocument();
    expect(screen.queryByRole('menu', { name: 'File' })).toBeNull();
  });

  it('does not open on hover alone', () => {
    setup();
    fireEvent.mouseEnter(menuButton(/^File/).parentElement!);
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('closes on Escape and returns focus to its button', () => {
    setup();
    const button = menuButton(/^File/);
    fireEvent.click(button);
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
    expect(button).toHaveFocus();
  });

  it('closes when clicking elsewhere', () => {
    setup();
    fireEvent.click(menuButton(/^File/));
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('can be driven from the keyboard', () => {
    const h = setup();
    const button = menuButton(/^Analyze/);
    button.focus();
    fireEvent.keyDown(button, { key: 'ArrowDown' });
    const items = screen.getAllByRole('menuitem');
    expect(items[0]).toHaveFocus();
    fireEvent.keyDown(items[0], { key: 'ArrowDown' });
    expect(items[1]).toHaveFocus();
    fireEvent.keyDown(items[1], { key: 'ArrowUp' });
    fireEvent.keyDown(items[0], { key: 'ArrowUp' });
    expect(items[items.length - 1]).toHaveFocus();                               // wraps around
    fireEvent.click(items[1]);
    expect(h.onSuggest).toHaveBeenCalledOnce();
  });

  it('disables items that are unavailable and explains why', () => {
    setup({ onCloud: undefined });
    fireEvent.click(menuButton(/^File/));
    const cloud = screen.getByRole('menuitem', { name: 'Cloud workflows…' });
    expect(cloud).toBeDisabled();
    expect(cloud).toHaveAttribute('title', 'Not available');
  });
});

describe('Toolbar — command palette', () => {
  const openPalette = () => fireEvent.click(screen.getByRole('button', { name: 'Search actions' }));
  const type = (text: string) => fireEvent.change(screen.getByRole('combobox', { name: 'Search actions' }), { target: { value: text } });

  it('opens from the button and from Ctrl+K, and closes on Escape', () => {
    setup();
    openPalette();
    expect(screen.getByRole('dialog', { name: 'Command palette' })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(screen.getByRole('dialog', { name: 'Command palette' })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('lists every action, including the ones inside menus', () => {
    setup();
    openPalette();
    const labels = screen.getAllByRole('option').map((o) => o.textContent ?? '');
    for (const wanted of ['Validate', 'Simulate', 'Tests', 'Generate with AI', 'Cloud workflows…', 'Safety checks', 'Mermaid diagram', 'Run history', 'Edit JSON']) {
      expect(labels.some((l) => l.includes(wanted))).toBe(true);
    }
  });

  it('filters by what is typed, matching the hint and group as well as the name', () => {
    setup();
    openPalette();
    type('share');
    expect(screen.getAllByRole('option')).toHaveLength(1);                       // only the cloud item mentions share links
    expect(screen.getByRole('option')).toHaveTextContent('Cloud workflows…');
    type('export code');
    expect(screen.getAllByRole('option')[0]).toHaveTextContent('Code (Python, LangGraph, MCP)');
    type('zzzz');
    expect(screen.getByText(/No action matches “zzzz”/)).toBeInTheDocument();
  });

  it('runs the highlighted action with Enter, moving with the arrow keys', () => {
    const h = setup();
    openPalette();
    type('validate');
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Enter' });
    expect(h.onValidate).toHaveBeenCalledOnce();
    expect(screen.queryByRole('dialog')).toBeNull();

    openPalette();
    type('safety');
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'ArrowDown' });
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'ArrowUp' });
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Enter' });
    expect(h.onSafety).toHaveBeenCalledOnce();
  });

  it('runs an action when clicked', () => {
    const h = setup();
    openPalette();
    fireEvent.click(screen.getByRole('option', { name: /Generate with AI/ }).querySelector('button')!);
    expect(h.onGenerate).toHaveBeenCalledOnce();
  });

  it('shows unavailable actions disabled with the reason and does not run them', () => {
    const h = setup({ canRefine: false, canUndo: false });
    openPalette();
    type('refine');
    const option = screen.getByRole('option');
    expect(option).toHaveAttribute('aria-disabled', 'true');
    expect(option).toHaveTextContent('Build a workflow first to refine it');
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Enter' });
    expect(h.onRefine).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toBeInTheDocument();                       // stays open
  });
});

describe('filterActions', () => {
  const actions: ActionItem[] = [
    { id: 'a', label: 'Open file…', group: 'File', hint: 'Open a workflow JSON file' },
    { id: 'b', label: 'Edit JSON', group: 'Export' },
  ];
  it('returns everything for an empty query and requires every word to match', () => {
    expect(filterActions(actions, '')).toHaveLength(2);
    expect(filterActions(actions, '  ')).toHaveLength(2);
    expect(filterActions(actions, 'json').map((a) => a.id)).toEqual(['a', 'b']);
    expect(filterActions(actions, 'json export').map((a) => a.id)).toEqual(['b']);
    expect(filterActions(actions, 'JSON FILE').map((a) => a.id)).toEqual(['a']);
    expect(filterActions(actions, 'nope')).toEqual([]);
  });
});
