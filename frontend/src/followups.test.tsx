import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { HelpIcon } from './components/HelpIcon';
import { Toolbar } from './components/Toolbar';
import LandingPage from './pages/LandingPage';
import { PassRateTrend } from './features/workflow/suites/PassRateTrend';
import { MAX_RECENT, pushRecent, readRecent } from './components/recentActions';
import { APP_VERSION } from './version';
import type { SuiteRunSummary } from './models/suites';

vi.mock('./context/AuthContext', () => ({
  useAuth: () => ({ user: { email: 'a@b.c' }, profile: { role: 'user', name: 'Ada' }, session: { access_token: 't' }, signOut: vi.fn() }),
}));

beforeEach(() => localStorage.clear());

describe('help icons link to the guide', () => {
  it('adds a "Read more" link to the matching section, opening in a new tab', () => {
    render(<HelpIcon title="Safety checks" body="Two checks." guide="safety-checks" />);
    fireEvent.click(screen.getByRole('button', { name: 'Help: Safety checks' }));
    const link = screen.getByRole('link', { name: 'Read more in the user guide' });
    expect(link).toHaveAttribute('href', '/guide#safety-checks');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('adds no link when there is no matching section', () => {
    render(<HelpIcon title="Anything" body="Text." />);
    fireEvent.click(screen.getByRole('button', { name: 'Help: Anything' }));
    expect(screen.queryByRole('link')).toBeNull();
  });
});

describe('landing page', () => {
  it('links to the user guide and shows the version', () => {
    render(<MemoryRouter><LandingPage /></MemoryRouter>);
    expect(screen.getAllByRole('link', { name: 'User guide' })[0]).toHaveAttribute('href', '/guide');
    expect(screen.getByTestId('landing-version')).toHaveTextContent(`v${APP_VERSION}`);
  });
});

const base = { workflowName: 'W', onNew: vi.fn(), onSave: vi.fn(), onOpen: vi.fn(), onOpenExamplePicker: vi.fn(), onValidate: vi.fn(), onGenerate: vi.fn(), onRefine: vi.fn(), onSimulate: vi.fn(), onEditJson: vi.fn(), onNameChange: vi.fn() };

describe('save state next to the workflow name', () => {
  it('says there are unsaved changes', () => {
    render(<MemoryRouter><Toolbar {...base} saveState={{ dirty: true, cloud: false }} /></MemoryRouter>);
    expect(screen.getByTestId('save-state')).toHaveTextContent('Unsaved changes');
  });
  it('unsaved wins over cloud: the cloud copy no longer matches', () => {
    render(<MemoryRouter><Toolbar {...base} saveState={{ dirty: true, cloud: true }} /></MemoryRouter>);
    expect(screen.getByTestId('save-state')).toHaveTextContent('Unsaved changes');
  });
  it('says when the cloud copy matches', () => {
    render(<MemoryRouter><Toolbar {...base} saveState={{ dirty: false, cloud: true }} /></MemoryRouter>);
    expect(screen.getByTestId('save-state')).toHaveTextContent('Saved to cloud');
  });
  it('shows nothing for a clean workflow that is not in the cloud, or when not told', () => {
    const { rerender } = render(<MemoryRouter><Toolbar {...base} saveState={{ dirty: false, cloud: false }} /></MemoryRouter>);
    expect(screen.queryByTestId('save-state')).toBeNull();
    rerender(<MemoryRouter><Toolbar {...base} /></MemoryRouter>);
    expect(screen.queryByTestId('save-state')).toBeNull();
  });
});

describe('recent actions', () => {
  it('keeps the newest first, without duplicates, and at most five', () => {
    let list: string[] = [];
    for (const id of ['a', 'b', 'c', 'd', 'e', 'f']) list = pushRecent(list, id);
    expect(list).toEqual(['f', 'e', 'd', 'c', 'b']);
    expect(list).toHaveLength(MAX_RECENT);
    expect(pushRecent(list, 'c')).toEqual(['c', 'f', 'e', 'd', 'b']);
    expect(readRecent()).toEqual(['c', 'f', 'e', 'd', 'b']);                       // persisted
  });

  it('survives junk or blocked storage', () => {
    localStorage.setItem('aiflow:recent-actions', '{not json');
    expect(readRecent()).toEqual([]);
    localStorage.setItem('aiflow:recent-actions', JSON.stringify(['ok', 7, null, 'fine']));
    expect(readRecent()).toEqual(['ok', 'fine']);
    localStorage.setItem('aiflow:recent-actions', '"a string"');
    expect(readRecent()).toEqual([]);
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(pushRecent(['x'], 'y')).toEqual(['y', 'x']);                             // still works in memory
    spy.mockRestore();
  });

  const openPalette = () => fireEvent.click(screen.getByRole('button', { name: 'Search actions' }));
  const optionNames = () => screen.getAllByRole('option').map((o) => o.querySelector('.cp-item-label')?.textContent);

  it('lists what you used most recently first, labelled Recent, until you type', () => {
    localStorage.setItem('aiflow:recent-actions', JSON.stringify(['check:safety', 'doc:save']));
    render(<MemoryRouter><Toolbar {...base} onSafety={vi.fn()} onCloud={vi.fn()} /></MemoryRouter>);
    openPalette();
    expect(optionNames().slice(0, 2)).toEqual(['Safety checks', 'Save to file…']);
    const first = screen.getAllByRole('option')[0];
    expect(within(first).getByText('Recent')).toBeInTheDocument();
    expect(optionNames().filter((n) => n === 'Safety checks')).toHaveLength(1);       // not listed twice
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'save' } });
    expect(screen.queryByText('Recent')).toBeNull();                                  // typing goes back to plain search
  });

  it('remembers an action chosen from the palette, and one chosen from a menu', () => {
    const onSafety = vi.fn();
    render(<MemoryRouter><Toolbar {...base} onSafety={onSafety} onExplain={vi.fn()} /></MemoryRouter>);
    openPalette();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'safety' } });
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Enter' });
    expect(onSafety).toHaveBeenCalledOnce();
    expect(readRecent()).toEqual(['check:safety']);

    fireEvent.click(screen.getByRole('button', { name: /^Analyze/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Explain' }));
    expect(readRecent()).toEqual(['check:explain', 'check:safety']);
  });

  it('does not remember opening the palette itself, and skips recents that are unavailable', () => {
    localStorage.setItem('aiflow:recent-actions', JSON.stringify(['check:safety']));
    render(<MemoryRouter><Toolbar {...base} /></MemoryRouter>);                        // no onSafety: that action is unavailable now
    fireEvent.click(screen.getByRole('button', { name: 'Help' }));
    fireEvent.click(screen.getByRole('menuitem', { name: /Search actions/ }));
    expect(readRecent()).toEqual(['check:safety']);
    expect(screen.queryByText('Recent')).toBeNull();
  });
});

describe('PassRateTrend', () => {
  const run = (id: string, passed: number, failed: number, over: Partial<SuiteRunSummary> = {}): SuiteRunSummary => ({
    id, suite_id: 's', status: 'complete', case_count: passed + failed, passed, failed, errors: 0, created_at: `2026-11-2${id}T10:00:00Z`, ...over,
  });

  it('draws nothing for fewer than two finished runs', () => {
    const { container, rerender } = render(<PassRateTrend runs={[run('1', 3, 0)]} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<PassRateTrend runs={[run('1', 3, 0), run('2', 0, 0), run('3', 2, 1, { status: 'running' }), run('4', 2, 1, { status: 'cancelled' })]} />);
    expect(container).toBeEmptyDOMElement();                                          // empty, running and cancelled runs do not count
  });

  it('plots finished runs oldest to newest and describes them for screen readers', () => {
    render(<PassRateTrend runs={[run('3', 2, 1), run('2', 3, 0), run('1', 1, 2)]} />);     // newest first, as listed
    const chart = screen.getByRole('img');
    expect(chart).toHaveAttribute('aria-label', 'Pass rate over the last 3 runs, oldest to newest: 33%, 100%, 67%');
    expect(screen.getByTestId('trend-summary')).toHaveTextContent('Latest 67% · down 33 points on the run before');
  });

  it('says when the latest run improved or stayed the same', () => {
    const { rerender } = render(<PassRateTrend runs={[run('2', 3, 0), run('1', 2, 1)]} />);
    expect(screen.getByTestId('trend-summary')).toHaveTextContent('up 33 points');
    rerender(<PassRateTrend runs={[run('2', 3, 0), run('1', 3, 0)]} />);
    expect(screen.getByTestId('trend-summary')).toHaveTextContent('same as the run before');
  });

  it('shows at most the last twelve runs', () => {
    const many = Array.from({ length: 20 }, (_, i) => run(String(i), 1, 0));
    render(<PassRateTrend runs={many} />);
    expect(screen.getByRole('img').getAttribute('aria-label')).toContain('last 12 runs');
  });
});
