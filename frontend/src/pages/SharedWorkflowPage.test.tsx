import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import SharedWorkflowPage from './SharedWorkflowPage';
import { NodeType } from '../models/workflow';

// The canvas needs a real layout engine; what matters here is what the page decides to show.
vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ nodes, nodesDraggable, nodesConnectable }: { nodes: unknown[]; nodesDraggable: boolean; nodesConnectable: boolean }) => (
    <div data-testid="flow" data-nodes={nodes.length} data-draggable={String(nodesDraggable)} data-connectable={String(nodesConnectable)} />
  ),
  ReactFlowProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Background: () => null,
  Controls: () => null,
  Handle: () => null,
  Position: { Top: 'top', Bottom: 'bottom' },
}));

const workflow = {
  version: '1.0', id: 'wf', name: 'W', description: 'Routes tickets', metadata: {}, edges: [],
  nodes: [
    { id: 's', type: NodeType.START, name: 'Start', position: { x: 0, y: 0 }, config: {} },
    { id: 'e', type: NodeType.END, name: 'End', position: { x: 0, y: 100 }, config: {} },
  ],
};

let seen: string[];
let reply: { status: number; body: unknown };

beforeEach(() => {
  seen = [];
  reply = { status: 200, body: { name: 'Public demo', workflow, shared_at: '2026-11-25T10:00:00Z' } };
  vi.stubGlobal('fetch', async (url: string, init: RequestInit) => {
    seen.push(`${init.method ?? 'GET'} ${url} auth=${JSON.stringify((init.headers as Record<string, string>).Authorization ?? null)}`);
    return { ok: reply.status < 400, status: reply.status, json: async () => reply.body } as Response;
  });
});
afterEach(() => vi.unstubAllGlobals());

const renderAt = (token: string) => render(
  <MemoryRouter initialEntries={[`/shared/${token}`]}>
    <Routes>
      <Route path="/shared/:token" element={<SharedWorkflowPage />} />
      <Route path="/login" element={<div>Login page</div>} />
    </Routes>
  </MemoryRouter>,
);

describe('SharedWorkflowPage', () => {
  it('shows the shared workflow read-only, without sending any sign-in', async () => {
    renderAt('abc123');
    expect(await screen.findByRole('heading', { name: 'Public demo' })).toBeInTheDocument();
    expect(screen.getByText(/Shared read-only · 2 steps · Routes tickets/)).toBeInTheDocument();
    const flow = screen.getByTestId('flow');
    expect(flow).toHaveAttribute('data-nodes', '2');
    expect(flow).toHaveAttribute('data-draggable', 'false');
    expect(flow).toHaveAttribute('data-connectable', 'false');
    expect(seen).toHaveLength(1);
    expect(seen[0]).toMatch(/^GET .*\/api\/shared\/abc123 auth=null$/);
  });

  it('offers a download and a way in, but no editing controls', async () => {
    renderAt('abc123');
    await screen.findByRole('heading', { name: 'Public demo' });
    expect(screen.getByRole('button', { name: 'Download JSON' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sign in to build your own' })).toHaveAttribute('href', '/login');
    expect(screen.queryByRole('button', { name: /save|delete|share/i })).toBeNull();
  });

  it('shows a clear message for a link that is off or invalid', async () => {
    reply = { status: 404, body: { detail: 'This link is not valid or is no longer shared.' } };
    renderAt('gone');
    expect(await screen.findByRole('alert')).toHaveTextContent('This link is not valid or is no longer shared.');
    expect(screen.getByRole('heading', { name: 'Workflow not available' })).toBeInTheDocument();
    expect(screen.queryByTestId('flow')).toBeNull();
  });

  it('encodes the token in the request', async () => {
    renderAt('a%2Fb');
    await screen.findByRole('heading', { name: 'Public demo' });
    expect(seen[0]).not.toContain('/api/shared/a/b');
  });
});
