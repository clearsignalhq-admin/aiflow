import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import LandingPage from './LandingPage';
import { CATALOG } from '../features/workflow/exampleCatalog';

vi.mock('../hooks/useAnalytics', () => ({ useAnalytics: () => ({ track: vi.fn() }) }));

const page = () => render(<MemoryRouter><LandingPage /></MemoryRouter>);
const repoRemote = () => {
  const config = readFileSync(join(__dirname, '..', '..', '..', '.git', 'config'), 'utf-8');
  return /url = (?:https:\/\/github\.com\/|git@github\.com:)([^\s]+?)(?:\.git)?\s/.exec(config)?.[1];
};

describe('landing page: links', () => {
  it('every GitHub link points at the real repository (the old address returned 404)', () => {
    page();
    const links = screen.getAllByRole('link').filter((a) => (a.getAttribute('href') ?? '').includes('github.com'));
    expect(links.length).toBeGreaterThanOrEqual(3);                                       // nav, hero, call to action, footer
    for (const a of links) {
      expect(a).toHaveAttribute('href', 'https://github.com/fuvito/aiflow');
      expect(a).toHaveAttribute('target', '_blank');
      expect(a).toHaveAttribute('rel', 'noopener noreferrer');
    }
  });

  it('agrees with the repository this code lives in', () => {
    const remote = repoRemote();
    if (!remote) return;                                                                   // not a git checkout (an exported copy)
    page();
    for (const a of screen.getAllByRole('link').filter((l) => (l.getAttribute('href') ?? '').includes('github.com'))) {
      expect(a.getAttribute('href')).toBe(`https://github.com/${remote}`);
    }
  });

  it('links to the user guide from the nav, the hero, the call to action and the footer', () => {
    page();
    const guide = screen.getAllByRole('link').filter((a) => a.getAttribute('href') === '/guide');
    expect(guide.length).toBeGreaterThanOrEqual(4);
    expect(screen.getByRole('navigation')).toContainElement(guide[0]);
  });
});

describe('landing page: what it says', () => {
  it('describes the product as it is now: designing, checking, testing and sharing', () => {
    page();
    expect(screen.getByText(/designing, checking, testing and sharing/i)).toBeInTheDocument();
    expect(screen.queryByText(/simulating, and evaluating/i)).toBeNull();
  });

  it('names the five stages, each with a description that mentions what is really there', () => {
    page();
    const text = document.body.textContent ?? '';
    for (const phrase of ['one of twelve examples', 'one-click fixes', 'safety checks', 'failure drill', 'test suites', 'read-only share links', 'LangGraph']) {
      expect(text, phrase).toContain(phrase);
    }
  });

  it('does not claim a model it does not default to', () => {
    page();
    expect(screen.queryByText('OpenAI GPT-4o')).toBeNull();
    expect(screen.getByText('OpenAI models')).toBeInTheDocument();
  });
});

describe('landing page: screenshots', () => {
  it('shows four real screenshots with descriptions, each from the user guide', () => {
    page();
    const shots = screen.getAllByRole('img');
    expect(shots).toHaveLength(4);
    for (const img of shots) {
      expect(img.getAttribute('src'), img.getAttribute('alt') ?? '').toMatch(/\.png/);
      expect((img.getAttribute('alt') ?? '').length).toBeGreaterThan(30);                 // a description, not a file name
      expect(img).toHaveAttribute('loading', 'lazy');
    }
    expect(screen.getByText('Know what a change broke.')).toBeInTheDocument();
  });

  it('uses screenshots that exist in the guide', () => {
    const source = readFileSync(join(__dirname, 'LandingPage.tsx'), 'utf-8');
    const used = [...source.matchAll(/user-guide\/images\/([^']+\.png)/g)].map((m) => m[1]);
    expect(used).toHaveLength(4);
    for (const file of used) expect(existsSync(join(__dirname, '..', '..', '..', 'docs', 'user-guide', 'images', file)), file).toBe(true);
  });
});

describe('landing page: example workflows', () => {
  it('shows every example the app offers, with its level and step count, read from the files', () => {
    page();
    const cards = screen.getAllByTestId('landing-example');
    expect(cards).toHaveLength(CATALOG.length);
    expect(cards.length).toBeGreaterThanOrEqual(12);
    for (const entry of CATALOG) {
      const name = (entry.json as { name: string }).name;
      const card = cards.find((c) => within(c).queryByRole('heading', { name }))!;
      expect(card, name).toBeTruthy();
      expect(card).toHaveTextContent(`${entry.nodeCount} steps`);
      expect(card).toHaveTextContent(entry.difficulty);
      expect(card).toHaveTextContent(entry.industry);
    }
    expect(screen.getByRole('heading', { name: `${CATALOG.length} example workflows` })).toBeInTheDocument();
  });

  it('no longer shows the invented examples', () => {
    page();
    for (const gone of ['Document Analysis', 'Review Pipeline']) expect(screen.queryByText(gone)).toBeNull();
    expect(screen.queryByText(/Generate any of these with a single sentence/i)).toBeNull();
  });

  it('says one example is flawed on purpose', () => {
    page();
    expect(screen.getByText(/flawed on\s+purpose/i)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Refund Request Handler' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Supply Chain Monitor' })).toBeInTheDocument();
  });

  it('keeps each description to its first sentence', () => {
    page();
    for (const card of screen.getAllByTestId('landing-example')) {
      const description = card.querySelector('.landing-example-desc')!.textContent ?? '';
      expect(description.length).toBeGreaterThan(20);
      expect(description.match(/\. /g) ?? []).toHaveLength(0);                             // a single sentence
    }
  });
});
