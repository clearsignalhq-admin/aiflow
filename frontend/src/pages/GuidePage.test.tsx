import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import GuidePage from './GuidePage';
import { MarkdownView } from '../components/MarkdownView';
import { Toolbar } from '../components/Toolbar';
import { AboutModal } from '../components/AboutModal';
import { parseInline, parseMarkdown, slugify } from '../utils/markdown';
import { fireEvent } from '@testing-library/react';

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: { email: 'a@b.c' }, profile: { role: 'user', name: 'Ada' }, session: { access_token: 't' }, signOut: vi.fn() }),
}));

const renderGuide = (path = '/guide') => render(<MemoryRouter initialEntries={[path]}><GuidePage /></MemoryRouter>);

describe('markdown: images, links and heading ids', () => {
  it('parses an image on its own line, and keeps neighbouring paragraphs apart', () => {
    expect(parseMarkdown('Before\n![Alt text](images/a.png)\nAfter')).toEqual([
      { type: 'paragraph', text: 'Before' },
      { type: 'image', alt: 'Alt text', src: 'images/a.png' },
      { type: 'paragraph', text: 'After' },
    ]);
  });

  it('parses links inside text without disturbing other formatting', () => {
    expect(parseInline('See [the guide](#intro) and **bold** or `code`.')).toEqual([
      { kind: 'text', text: 'See ' },
      { kind: 'link', text: 'the guide', href: '#intro' },
      { kind: 'text', text: ' and ' },
      { kind: 'bold', text: 'bold' },
      { kind: 'text', text: ' or ' },
      { kind: 'code', text: 'code' },
      { kind: 'text', text: '.' },
    ]);
  });

  it('makes heading ids the way GitHub does', () => {
    expect(slugify('Quick start (five minutes)')).toBe('quick-start-five-minutes');
    expect(slugify('Saving, versions and sharing')).toBe('saving-versions-and-sharing');
    expect(slugify('  Words used in AiFlow ')).toBe('words-used-in-aiflow');
  });

  it('renders heading ids, safe links and resolved images', () => {
    render(<MarkdownView source={'## Some Heading\n\n[in page](#some-heading) [site](https://example.com) [app](/app)\n\n![A picture](images/p.png)'} resolveImage={(s) => (s === 'images/p.png' ? '/p.png' : null)} />);
    expect(screen.getByRole('heading', { name: 'Some Heading' })).toHaveAttribute('id', 'some-heading');
    expect(screen.getByRole('link', { name: 'in page' })).toHaveAttribute('href', '#some-heading');
    const external = screen.getByRole('link', { name: 'site' });
    expect(external).toHaveAttribute('target', '_blank');
    expect(external).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByRole('link', { name: 'app' })).toHaveAttribute('href', '/app');
    expect(screen.getByRole('img', { name: 'A picture' })).toHaveAttribute('src', '/p.png');
  });

  it('never turns an unsafe address into a link, and never loads an unresolved image', () => {
    render(<MarkdownView source={'[bad](javascript:alert(1)) [file](C:/secret.txt) [rel](../x)\n\n![Missing shot](images/none.png)'} resolveImage={() => null} />);
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByText('bad')).toBeInTheDocument();
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.getByText('Missing shot')).toBeInTheDocument();                       // its description stands in
  });

  it('renders no image at all without a resolver', () => {
    render(<MarkdownView source={'![Only text](images/a.png)'} />);
    expect(screen.queryByRole('img')).toBeNull();
  });
});

describe('GuidePage', () => {
  it('shows the guide with a contents list that links to every section', () => {
    renderGuide();
    const toc = screen.getByRole('navigation', { name: 'Contents' });
    const links = within(toc).getAllByRole('link');
    expect(links.length).toBeGreaterThanOrEqual(12);
    expect(within(toc).getByRole('link', { name: 'Quick start (five minutes)' })).toHaveAttribute('href', '#quick-start-five-minutes');
    // every contents link points at a heading that exists
    for (const l of links) {
      const id = l.getAttribute('href')!.slice(1);
      expect(document.getElementById(id), id).not.toBeNull();
    }
  });

  it('renders the real guide: screenshots resolve, and the in-text contents links work', () => {
    renderGuide();
    const content = screen.getByTestId('guide-content');
    const images = within(content).getAllByRole('img');
    expect(images.length).toBeGreaterThanOrEqual(20);
    for (const img of images) expect(img.getAttribute('src'), img.getAttribute('alt') ?? '').toBeTruthy();
    for (const a of content.querySelectorAll<HTMLAnchorElement>('a[href^="#"]')) {
      expect(document.getElementById(a.getAttribute('href')!.slice(1)), a.getAttribute('href')!).not.toBeNull();
    }
  });

  it('has an entry point back to the app', () => {
    renderGuide();
    expect(screen.getByRole('link', { name: 'Open the app' })).toHaveAttribute('href', '/app');
  });

  it('covers the features it promises', () => {
    renderGuide();
    const text = screen.getByTestId('guide-content').textContent ?? '';
    for (const phrase of ['Supply Chain Monitor', 'Suggest changes', 'failure drill', 'Compare with', 'Share', 'Ctrl+K', 'AI request']) {
      expect(text).toContain(phrase);
    }
  });
});

describe('Help menu and About link to the guide', () => {
  const base = { workflowName: 'W', onNew: vi.fn(), onSave: vi.fn(), onOpen: vi.fn(), onOpenExamplePicker: vi.fn(), onValidate: vi.fn(), onGenerate: vi.fn(), onRefine: vi.fn(), onSimulate: vi.fn(), onEditJson: vi.fn(), onNameChange: vi.fn() };

  it('opens the guide from the Help menu', () => {
    const onGuide = vi.fn();
    render(<MemoryRouter><Toolbar {...base} onGuide={onGuide} onAbout={vi.fn()} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Help' }));
    expect(screen.getAllByRole('menuitem').map((i) => i.querySelector('.tb-menu-item-label')?.textContent)).toEqual(['User guide', 'Search actions', 'About AiFlow']);
    fireEvent.click(screen.getByRole('menuitem', { name: 'User guide' }));
    expect(onGuide).toHaveBeenCalledOnce();
  });

  it('finds the guide in the action search', () => {
    render(<MemoryRouter><Toolbar {...base} onGuide={vi.fn()} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Search actions' }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'guide' } });
    expect(screen.getByRole('option')).toHaveTextContent('User guide');
  });

  it('links to the guide from the About dialog', () => {
    render(<AboutModal backend={{ state: 'loading', version: null, commit: null }} onClose={vi.fn()} />);
    const link = screen.getByRole('link', { name: 'Read the user guide' });
    expect(link).toHaveAttribute('href', '/guide');
    expect(link).toHaveAttribute('target', '_blank');
  });
});
