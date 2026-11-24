import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { CloudModal } from './CloudModal';
import { NodeType } from '../../models/workflow';
import type { Workflow } from '../../models/workflow';

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ session: { access_token: 'tok' }, profile: { role: 'user' } }),
}));
vi.mock('../../utils/download', () => ({ copyText: vi.fn(async () => true), downloadText: vi.fn() }));

const workflow: Workflow = {
  version: '1.0', id: 'wf', name: 'Triage', description: '',
  nodes: [{ id: 's', type: NodeType.START, name: 'Start', position: { x: 0, y: 0 }, config: {} }],
  edges: [], metadata: {},
};
const item = (id: string, name: string, over: Record<string, unknown> = {}) => ({ id, name, version_count: 2, shared: false, updated_at: '2026-11-25T10:00:00Z', ...over });
const detail = (id: string, over: Record<string, unknown> = {}) => ({ ...item(id, 'Triage'), workflow, share_token: null, new_version: true, ...over });

type Call = { method: string; path: string; body: unknown };
let calls: Call[];
let routes: Record<string, () => { status: number; body: unknown }>;

beforeEach(() => {
  calls = [];
  routes = { 'GET /cloud/workflows': () => ({ status: 200, body: [item('a', 'Alpha'), item('b', 'Beta', { shared: true })] }) };
  vi.stubGlobal('fetch', async (url: string, init: RequestInit) => {
    const path = String(url).split('/api')[1];
    const method = init.method ?? 'GET';
    calls.push({ method, path, body: init.body ? JSON.parse(String(init.body)) : undefined });
    const key = `${method} ${path.replace(/[0-9a-f-]{1,}(?=\/|$|\?)/g, (m) => (m === 'a' || m === 'b' ? ':id' : m))}`;
    const hit = routes[`${method} ${path}`] ?? routes[key] ?? (() => ({ status: 404, body: { detail: `no route ${method} ${path}` } }));
    const { status, body } = hit();
    return { ok: status < 400, status, json: async () => body } as Response;
  });
  vi.stubGlobal('confirm', vi.fn(() => true));
});
afterEach(() => vi.unstubAllGlobals());

const open = (over: Partial<React.ComponentProps<typeof CloudModal>> = {}) => {
  const props = { workflow, cloudId: null as string | null, onOpen: vi.fn(), onCloudIdChange: vi.fn(), onClose: vi.fn(), ...over };
  render(<CloudModal {...props} />);
  return props;
};
const card = async (name: string) => (await screen.findAllByTestId('cloud-item')).find((c) => c.textContent?.includes(name))!;

describe('CloudModal — list and save', () => {
  it('lists cloud workflows with version and shared state', async () => {
    open();
    expect(await card('Alpha')).toHaveTextContent('v2');
    expect(await card('Beta')).toHaveTextContent('shared');
  });

  it('says so when nothing is saved yet', async () => {
    routes['GET /cloud/workflows'] = () => ({ status: 200, body: [] });
    open();
    expect(await screen.findByTestId('cloud-empty')).toBeInTheDocument();
  });

  it('saves the workflow on screen as a new cloud workflow and ties the editor to it', async () => {
    routes['POST /cloud/workflows'] = () => ({ status: 201, body: detail('new', { name: 'Triage v1' }) });
    const p = open();
    await screen.findByText('Alpha');
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Triage v1' } });
    fireEvent.change(screen.getByLabelText('Version note'), { target: { value: 'first cut' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save as new cloud workflow' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Saved “Triage v1” to the cloud.');
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({ name: 'Triage v1', workflow, label: 'first cut' });
    expect(p.onCloudIdChange).toHaveBeenCalledWith('new');
  });

  it('offers Save changes only for the workflow open in the editor, and reports an unchanged save', async () => {
    routes['PUT /cloud/workflows/:id'] = () => ({ status: 200, body: detail('a', { new_version: false }) });
    open({ cloudId: 'a' });
    expect(within(await card('Beta')).queryByRole('button', { name: /^Save to/ })).toBeNull();
    fireEvent.click(within(await card('Alpha')).getByRole('button', { name: 'Save to Alpha' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Nothing has changed since the last save.');
  });

  it('reports the new version number after a changing save', async () => {
    routes['PUT /cloud/workflows/:id'] = () => ({ status: 200, body: detail('a', { version_count: 3 }) });
    const p = open({ cloudId: 'a' });
    fireEvent.click(within(await card('Alpha')).getByRole('button', { name: 'Save to Alpha' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Saved as version 3.');
    expect(p.onCloudIdChange).toHaveBeenCalledWith('a');
  });

  it('shows server errors such as the per-user limit', async () => {
    routes['POST /cloud/workflows'] = () => ({ status: 409, body: { detail: 'You can keep at most 30 workflows in the cloud. Delete one first.' } });
    open();
    await screen.findByText('Alpha');
    fireEvent.click(screen.getByRole('button', { name: 'Save as new cloud workflow' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('at most 30 workflows');
  });
});

describe('CloudModal — open and delete', () => {
  it('opens a workflow into the editor and closes', async () => {
    routes['GET /cloud/workflows/:id'] = () => ({ status: 200, body: detail('a') });
    const p = open();
    fireEvent.click(within(await card('Alpha')).getByRole('button', { name: 'Open Alpha' }));
    await waitFor(() => expect(p.onOpen).toHaveBeenCalledWith(workflow, 'a'));
    expect(p.onClose).toHaveBeenCalled();
  });

  it('asks before deleting, and unties the editor if it was the open one', async () => {
    routes['DELETE /cloud/workflows/:id'] = () => ({ status: 204, body: null });
    const p = open({ cloudId: 'a' });
    fireEvent.click(within(await card('Alpha')).getByRole('button', { name: 'Delete Alpha' }));
    await waitFor(() => expect(p.onCloudIdChange).toHaveBeenCalledWith(null));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('Delete “Alpha” and all 2 of its versions'));
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true);
  });

  it('does nothing when the delete is not confirmed', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false));
    open();
    fireEvent.click(within(await card('Alpha')).getByRole('button', { name: 'Delete Alpha' }));
    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
  });
});

describe('CloudModal — versions', () => {
  const versions = [
    { version: 2, label: 'added approval', created_at: '2026-11-25T10:00:00Z', node_count: 5, edge_count: 4 },
    { version: 1, label: null, created_at: '2026-11-24T10:00:00Z', node_count: 3, edge_count: 2 },
  ];

  it('lists versions, shows what changed since one, and can restore an older one', async () => {
    routes['GET /cloud/workflows/:id/versions'] = () => ({ status: 200, body: versions });
    routes['GET /cloud/workflows/:id/diff?base=1'] = () => ({ status: 200, body: { base_version: 1, head_version: null, diff: { changed: true, edges: [], nodes: [{ node_id: 'n', name: 'Approval', change: 'added', fields: [] }] } } });
    routes['POST /cloud/workflows/:id/versions/1/restore'] = () => ({ status: 200, body: detail('a', { version_count: 3 }) });
    const p = open({ cloudId: 'a' });
    fireEvent.click(within(await card('Alpha')).getByRole('button', { name: 'Versions of Alpha' }));
    const panel = await screen.findByTestId('versions');
    expect(panel).toHaveTextContent('“added approval”');
    expect(within(panel).queryByRole('button', { name: 'Restore version 2' })).toBeNull();       // the current one cannot be restored

    fireEvent.click(within(panel).getByRole('button', { name: 'Changes since version 1' }));
    expect(await screen.findByTestId('version-diff')).toHaveTextContent('Added step “Approval”');

    fireEvent.click(within(panel).getByRole('button', { name: 'Restore version 1' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Version 1 restored as version 3.');
    expect(p.onOpen).toHaveBeenCalledWith(workflow, 'a');                                        // the editor follows the cloud copy
  });

  it('says when the current copy equals the chosen version', async () => {
    routes['GET /cloud/workflows/:id/versions'] = () => ({ status: 200, body: versions });
    routes['GET /cloud/workflows/:id/diff?base=1'] = () => ({ status: 200, body: { base_version: 1, head_version: null, diff: { changed: false, edges: [], nodes: [] } } });
    open();
    fireEvent.click(within(await card('Alpha')).getByRole('button', { name: 'Versions of Alpha' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Changes since version 1' }));
    expect(await screen.findByTestId('version-diff')).toHaveTextContent('identical to this version');
  });

  it('hides the panel when Versions is pressed again', async () => {
    routes['GET /cloud/workflows/:id/versions'] = () => ({ status: 200, body: versions });
    open();
    const button = within(await card('Alpha')).getByRole('button', { name: 'Versions of Alpha' });
    fireEvent.click(button);
    await screen.findByTestId('versions');
    fireEvent.click(button);
    await waitFor(() => expect(screen.queryByTestId('versions')).toBeNull());
  });
});

describe('CloudModal — sharing', () => {
  it('turns sharing on and shows a copyable link, then turns it off', async () => {
    routes['POST /cloud/workflows/:id/share'] = () => ({ status: 200, body: { share_token: 'T'.repeat(43) } });
    routes['DELETE /cloud/workflows/:id/share'] = () => ({ status: 200, body: { share_token: null } });
    open();
    fireEvent.click(within(await card('Alpha')).getByRole('button', { name: 'Share Alpha' }));
    routes['GET /cloud/workflows'] = () => ({ status: 200, body: [item('a', 'Alpha', { shared: true }), item('b', 'Beta', { shared: true })] });
    const link = await screen.findAllByLabelText('Share link');
    expect((link[0] as HTMLInputElement).value).toBe(`${window.location.origin}/shared/${'T'.repeat(43)}`);
    fireEvent.click(screen.getAllByRole('button', { name: 'Copy link' })[0]);
    expect(await screen.findByText('Copied')).toBeInTheDocument();

    routes['GET /cloud/workflows'] = () => ({ status: 200, body: [item('a', 'Alpha'), item('b', 'Beta', { shared: true })] });
    fireEvent.click(within(await card('Alpha')).getByRole('button', { name: 'Stop sharing Alpha' }));
    expect(await screen.findByText(/link has been turned off/)).toBeInTheDocument();
  });

  it('can show the link of an already-shared workflow on request', async () => {
    routes['POST /cloud/workflows/:id/share'] = () => ({ status: 200, body: { share_token: 'S'.repeat(43) } });
    open();
    fireEvent.click(within(await card('Beta')).getByRole('button', { name: 'Show link' }));
    expect(await screen.findByLabelText('Share link')).toHaveValue(`${window.location.origin}/shared/${'S'.repeat(43)}`);
  });
});
