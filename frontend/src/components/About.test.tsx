import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, renderHook } from '@testing-library/react';
import { AboutModal } from './AboutModal';
import { VersionBanner } from './VersionBanner';
import { Toolbar } from './Toolbar';
import { useBackendVersion } from '../hooks/useBackendVersion';
import { compareVersions, versionSummary } from '../utils/version';
import type { BackendVersion } from '../utils/version';
import { APP_VERSION } from '../version';

vi.mock('../utils/download', () => ({ copyText: vi.fn(async () => true), downloadText: vi.fn() }));
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: { email: 'a@b.c' }, profile: { role: 'user', name: 'Ada' }, session: { access_token: 't' }, signOut: vi.fn() }),
}));
vi.mock('react-router-dom', () => ({ Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a> }));

const ok = (version: string | null, commit: string | null = 'abc1234'): BackendVersion => ({ state: 'ok', version, commit });
const bump = (v: string, part: 'major' | 'minor' | 'patch', by: number) => {
  const [a, b, c] = v.split('.').map(Number);
  return part === 'major' ? `${a + by}.${b}.${c}` : part === 'minor' ? `${a}.${b + by}.${c}` : `${a}.${b}.${c + by}`;
};

describe('compareVersions', () => {
  it('treats a different patch number as compatible', () => {
    expect(compareVersions('0.9.0', '0.9.0')).toBe('match');
    expect(compareVersions('0.9.0', '0.9.7')).toBe('match');
    expect(compareVersions('0.9.4', '0.9.1')).toBe('match');
  });
  it('flags a different minor or major number', () => {
    expect(compareVersions('0.9.0', '0.10.0')).toBe('frontend-older');
    expect(compareVersions('0.10.0', '0.9.5')).toBe('frontend-newer');
    expect(compareVersions('0.9.0', '1.0.0')).toBe('frontend-older');
    expect(compareVersions('2.0.0', '1.9.9')).toBe('frontend-newer');
  });
  it('is unknown when either side is missing or unreadable', () => {
    expect(compareVersions('0.9.0', null)).toBe('unknown');
    expect(compareVersions('0.9.0', undefined)).toBe('unknown');
    expect(compareVersions('0.9.0', 'banana')).toBe('unknown');
    expect(compareVersions('dev', '0.9.0')).toBe('unknown');
  });
  it('ignores a suffix such as -beta', () => {
    expect(compareVersions('0.9.0', '0.9.0-beta.1')).toBe('match');
  });
});

describe('versionSummary', () => {
  const fe = { version: '0.9.0', commit: 'f00', date: '2026-11-24' };
  it('is one pasteable line', () => {
    expect(versionSummary(fe, ok('0.9.1', 'b4r'))).toBe('AiFlow 0.9.0 (page f00, built 2026-11-24) · server 0.9.1 (b4r)');
    expect(versionSummary(fe, { state: 'unreachable', version: null, commit: null })).toContain('server unreachable');
  });
});

describe('AboutModal', () => {
  it('shows the version, build info and the changelog', () => {
    render(<AboutModal backend={ok(APP_VERSION, 'abc1234')} onClose={vi.fn()} />);
    expect(screen.getByTestId('about-version')).toHaveTextContent(APP_VERSION);
    expect(screen.getByTestId('about-server')).toHaveTextContent(`${APP_VERSION} (commit abc1234)`);
    expect(screen.getByTestId('about-changelog')).toHaveTextContent(`${APP_VERSION} — `);       // newest entry is the running version
    expect(screen.getByTestId('about-changelog')).not.toHaveTextContent('AiFlow follows');      // the intro is skipped
    expect(screen.getByTestId('about-relation')).toHaveTextContent('same version');
  });

  it('describes the server in each state', () => {
    const { rerender } = render(<AboutModal backend={{ state: 'loading', version: null, commit: null }} onClose={vi.fn()} />);
    expect(screen.getByTestId('about-server')).toHaveTextContent('checking…');
    rerender(<AboutModal backend={{ state: 'unreachable', version: null, commit: null }} onClose={vi.fn()} />);
    expect(screen.getByTestId('about-server')).toHaveTextContent('could not be reached');
    rerender(<AboutModal backend={ok(null, null)} onClose={vi.fn()} />);
    expect(screen.getByTestId('about-server')).toHaveTextContent('version not reported');
    rerender(<AboutModal backend={ok(APP_VERSION, 'unknown')} onClose={vi.fn()} />);
    expect(screen.getByTestId('about-server').textContent).not.toContain('commit');
  });

  it('warns when the server is newer or older than the page', () => {
    const { rerender } = render(<AboutModal backend={ok(bump(APP_VERSION, 'minor', 1))} onClose={vi.fn()} />);
    expect(screen.getByTestId('about-relation')).toHaveTextContent('Reload the page');
    expect(screen.getByRole('alert')).toBeInTheDocument();
    rerender(<AboutModal backend={ok('0.0.1')} onClose={vi.fn()} />);
    expect(screen.getByTestId('about-relation')).toHaveTextContent('page is newer than the server');
  });

  it('shows no relation line when the server version is unknown', () => {
    render(<AboutModal backend={{ state: 'unreachable', version: null, commit: null }} onClose={vi.fn()} />);
    expect(screen.queryByTestId('about-relation')).toBeNull();
  });

  it('copies version info and closes on Escape', async () => {
    const { copyText } = await import('../utils/download');
    const onClose = vi.fn();
    render(<AboutModal backend={ok(APP_VERSION, 'abc1234')} onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: 'Copy version info' }));
    expect(await screen.findByText('Copied')).toBeInTheDocument();
    expect(vi.mocked(copyText).mock.calls[0][0]).toMatch(new RegExp(`^AiFlow ${APP_VERSION.replace(/\./g, '\\.')} .* server ${APP_VERSION.replace(/\./g, '\\.')} \\(abc1234\\)$`));
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});

describe('VersionBanner', () => {
  it('stays hidden when versions match, are unknown, or are loading', () => {
    for (const b of [ok(APP_VERSION), ok(bump(APP_VERSION, 'patch', 3)), ok(null), { state: 'loading', version: null, commit: null } as BackendVersion, { state: 'unreachable', version: null, commit: null } as BackendVersion]) {
      const { unmount } = render(<VersionBanner backend={b} />);
      expect(screen.queryByTestId('version-banner')).toBeNull();
      unmount();
    }
  });

  it('offers a reload when the server is newer, and can be dismissed', () => {
    const reload = vi.fn();
    vi.stubGlobal('location', { ...window.location, reload });
    render(<VersionBanner backend={ok(bump(APP_VERSION, 'minor', 1))} />);
    expect(screen.getByTestId('version-banner')).toHaveTextContent('A newer version of AiFlow is available');
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    expect(reload).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByTestId('version-banner')).toBeNull();
    vi.unstubAllGlobals();
  });

  it('warns without a reload button when the page is ahead of the server', () => {
    render(<VersionBanner backend={ok('0.0.1')} />);
    expect(screen.getByTestId('version-banner')).toHaveTextContent('newer than the server');
    expect(screen.queryByRole('button', { name: 'Reload' })).toBeNull();
  });
});

describe('useBackendVersion', () => {
  beforeEach(() => vi.unstubAllGlobals());
  afterEach(() => vi.unstubAllGlobals());
  const respond = (status: number, body: unknown) =>
    vi.stubGlobal('fetch', async () => ({ ok: status < 400, status, json: async () => body }) as Response);

  it('reads the version and commit from the health endpoint', async () => {
    respond(200, { status: 'ok', version: '0.9.2', commit: 'abc' });
    const { result } = renderHook(() => useBackendVersion());
    expect(result.current.state).toBe('loading');
    await waitFor(() => expect(result.current).toEqual({ state: 'ok', version: '0.9.2', commit: 'abc' }));
  });

  it('copes with an older server that reports no version', async () => {
    respond(200, { status: 'ok' });
    const { result } = renderHook(() => useBackendVersion());
    await waitFor(() => expect(result.current).toEqual({ state: 'ok', version: null, commit: null }));
  });

  it('reports an unreachable or failing server without throwing', async () => {
    vi.stubGlobal('fetch', async () => { throw new Error('offline'); });
    const first = renderHook(() => useBackendVersion());
    await waitFor(() => expect(first.result.current.state).toBe('unreachable'));
    respond(503, null);
    const second = renderHook(() => useBackendVersion());
    await waitFor(() => expect(second.result.current.state).toBe('unreachable'));
  });
});

describe('Toolbar — Help menu', () => {
  const base = { workflowName: 'W', onNew: vi.fn(), onSave: vi.fn(), onOpen: vi.fn(), onOpenExamplePicker: vi.fn(), onValidate: vi.fn(), onGenerate: vi.fn(), onRefine: vi.fn(), onSimulate: vi.fn(), onEditJson: vi.fn(), onNameChange: vi.fn() };

  it('opens About from the Help menu', () => {
    const onAbout = vi.fn();
    render(<Toolbar {...base} onAbout={onAbout} />);
    fireEvent.click(screen.getByRole('button', { name: 'Help' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'About AiFlow' }));
    expect(onAbout).toHaveBeenCalledOnce();
  });

  it('opens the command palette from the Help menu', () => {
    render(<Toolbar {...base} onAbout={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Help' }));
    fireEvent.click(screen.getByRole('menuitem', { name: /Search actions/ }));
    expect(screen.getByRole('dialog', { name: 'Command palette' })).toBeInTheDocument();
  });

  it('lists About in the command palette too', () => {
    render(<Toolbar {...base} onAbout={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Search actions' }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'about' } });
    expect(screen.getByRole('option')).toHaveTextContent('About AiFlow');
  });
});
