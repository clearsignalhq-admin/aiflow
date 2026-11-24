import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { parseInline, parseMarkdown, splitRow } from '../../utils/markdown';
import { MarkdownView } from '../../components/MarkdownView';
import { ExplainModal } from './ExplainModal';
import * as download from '../../utils/download';
import { NodeType } from '../../models/workflow';
import type { Workflow } from '../../models/workflow';

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ session: { access_token: 'tok' } }),
}));

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
beforeEach(() => { fetchMock.mockReset(); vi.restoreAllMocks(); });
const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });

const SAMPLE = `# Support Bot

Answers questions.

In short: 2 steps.

## At a glance

| | |
|---|---|
| Steps | 2 |
| Cost | $0.0020 |

## How it works

1. **Start** — begins here.
   - Then: **Ask**
2. **Ask** — asks an AI model (gpt-4o-mini). Instruction: “Be nice”
   - Produces \`reply\` (string).

## People in the loop

- **Review** — “Check it”
- Second item

---
_Estimates are rough._
`;

describe('parseMarkdown', () => {
  const blocks = parseMarkdown(SAMPLE);

  it('recognises headings, paragraphs, rules, tables and lists', () => {
    expect(blocks.map((b) => b.type)).toEqual(['heading', 'paragraph', 'paragraph', 'heading', 'table', 'heading', 'ol', 'heading', 'ul', 'rule', 'paragraph']);
    expect(blocks[0]).toEqual({ type: 'heading', level: 1, text: 'Support Bot' });
  });

  it('parses a table with its header and rows', () => {
    expect(blocks[4]).toEqual({ type: 'table', header: ['', ''], rows: [['Steps', '2'], ['Cost', '$0.0020']] });
  });

  it('nests bullets under numbered items', () => {
    const ol = blocks[6];
    expect(ol.type === 'ol' && ol.items.map((i) => i.children.length)).toEqual([1, 1]);
    expect(ol.type === 'ol' && ol.items[1].children[0]).toBe('Produces `reply` (string).');
  });

  it('joins wrapped paragraph lines and stops at structure', () => {
    expect(parseMarkdown('one\ntwo\n\n- a\n- b')).toEqual([
      { type: 'paragraph', text: 'one two' }, { type: 'ul', items: ['a', 'b'] },
    ]);
  });

  it('handles empty input and CRLF', () => {
    expect(parseMarkdown('')).toEqual([]);
    expect(parseMarkdown('# A\r\n\r\ntext')).toHaveLength(2);
  });

  it('splits table rows on unescaped pipes only', () => {
    expect(splitRow('| a \\| b | c |')).toEqual(['a | b', 'c']);
    expect(splitRow('|x|y|')).toEqual(['x', 'y']);
  });
});

describe('parseInline', () => {
  it('finds bold, italic and code, leaving the rest as text', () => {
    expect(parseInline('a **b** `c` _d_ *e* f')).toEqual([
      { kind: 'text', text: 'a ' }, { kind: 'bold', text: 'b' }, { kind: 'text', text: ' ' }, { kind: 'code', text: 'c' },
      { kind: 'text', text: ' ' }, { kind: 'italic', text: 'd' }, { kind: 'text', text: ' ' }, { kind: 'italic', text: 'e' }, { kind: 'text', text: ' f' },
    ]);
  });

  it('does not treat snake_case or lone asterisks as formatting', () => {
    expect(parseInline('my_field_name and 2 * 3')).toEqual([{ kind: 'text', text: 'my_field_name and 2 * 3' }]);
  });
});

describe('MarkdownView', () => {
  it('renders the document structure', () => {
    render(<MarkdownView source={SAMPLE} />);
    expect(screen.getByRole('heading', { level: 2, name: 'Support Bot' })).toBeInTheDocument();      // # becomes h2 inside a dialog
    expect(screen.getByRole('heading', { level: 3, name: 'How it works' })).toBeInTheDocument();
    const table = screen.getByRole('table');
    expect(within(table).getByText('$0.0020')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem').length).toBeGreaterThanOrEqual(5);
    expect(screen.getByText('reply').tagName).toBe('CODE');
  });

  it('never turns text into HTML', () => {
    const { container } = render(<MarkdownView source={'<img src=x onerror=alert(1)> **ok**\n\n<script>alert(1)</script>'} />);
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('script')).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>');
    expect(screen.getByText('ok').tagName).toBe('STRONG');
  });
});

describe('ExplainModal', () => {
  const workflow: Workflow = {
    version: '1.0', id: 'w', name: 'Support Bot', description: '',
    nodes: [{ id: 's', type: NodeType.START, name: 'Start', position: { x: 0, y: 0 }, config: {} }], edges: [], metadata: {},
  };

  it('asks the backend with the token and shows the explanation', async () => {
    fetchMock.mockResolvedValue(ok({ markdown: SAMPLE }));
    render(<ExplainModal workflow={workflow} onClose={vi.fn()} />);
    expect(await screen.findByRole('heading', { name: 'Support Bot' })).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/workflows/explain');
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(JSON.parse(init.body)).toEqual({ workflow });
  });

  it('shows a readable error and no document when the request fails', async () => {
    fetchMock.mockResolvedValue(ok({ detail: 'Access pending approval.' }, 403));
    render(<ExplainModal workflow={workflow} onClose={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Access pending approval.');
    expect(screen.getByText('Copy Markdown')).toBeDisabled();
  });

  it('copies and downloads the Markdown, and can refresh', async () => {
    fetchMock.mockResolvedValue(ok({ markdown: SAMPLE }));
    const copy = vi.spyOn(download, 'copyText').mockResolvedValue(true);
    const save = vi.spyOn(download, 'downloadText').mockImplementation(() => undefined);
    render(<ExplainModal workflow={workflow} onClose={vi.fn()} />);
    await screen.findByRole('heading', { name: 'Support Bot' });

    fireEvent.click(screen.getByText('Copy Markdown'));
    expect(await screen.findByText('Copied')).toBeInTheDocument();
    expect(copy).toHaveBeenCalledWith(SAMPLE);

    fireEvent.click(screen.getByText('Download .md'));
    expect(save).toHaveBeenCalledWith(SAMPLE, 'support-bot-explained.md', 'text/markdown');

    fireEvent.click(screen.getByText('Refresh'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it('closes on Escape', async () => {
    fetchMock.mockResolvedValue(ok({ markdown: '# x' }));
    const onClose = vi.fn();
    render(<ExplainModal workflow={workflow} onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});
