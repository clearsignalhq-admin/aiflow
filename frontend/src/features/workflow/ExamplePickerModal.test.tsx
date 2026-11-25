import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { ExamplePickerModal } from './ExamplePickerModal';
import { CATALOG } from './exampleCatalog';

// Every example file in the repository, whether or not the picker lists it.
const FILES = import.meta.glob('../../../../examples/*/*.json', { eager: true, import: 'default' }) as Record<string, { id: string; name: string; nodes: unknown[]; metadata: { difficulty: string } }>;

const open = () => {
  const onSelect = vi.fn();
  render(<ExamplePickerModal onClose={vi.fn()} onSelect={onSelect} />);
  return onSelect;
};
const cards = () => screen.getAllByRole('button').filter((b) => b.className.includes('example-card'));

describe('example catalog', () => {
  it('lists every example file in the repository (a new file must be added to the picker)', () => {
    const listed = CATALOG.map((e) => (e.json as { id: string }).id).sort();
    const onDisk = Object.values(FILES).map((f) => f.id).sort();
    expect(listed).toEqual(onDisk);
    expect(listed.length).toBeGreaterThanOrEqual(12);
  });

  it('reads difficulty, industry, tags and step count from the file, so they cannot go stale', () => {
    for (const e of CATALOG) {
      const file = e.json as { nodes: unknown[]; metadata: { difficulty: string; industry: string; tags: string[] } };
      expect(e.nodeCount).toBe(file.nodes.length);
      expect(e.difficulty).toBe(file.metadata.difficulty);
      expect(e.industry).toBe(file.metadata.industry);
      expect(e.tags).toEqual(file.metadata.tags);
    }
  });

  it('puts every example in the tier its folder says', () => {
    for (const [path, file] of Object.entries(FILES)) {
      expect(path).toContain(`/examples/${file.metadata.difficulty}/`);
    }
  });
});

describe('ExamplePickerModal', () => {
  it('shows every example under its tier, with its step count', () => {
    open();
    expect(cards()).toHaveLength(CATALOG.length);
    for (const e of CATALOG) {
      const card = cards().find((c) => c.textContent?.includes((e.json as { name: string }).name))!;
      expect(card, (e.json as { name: string }).name).toBeTruthy();
      expect(card).toHaveTextContent(`${e.nodeCount} nodes`);
    }
    for (const label of ['Easy', 'Medium', 'Complex']) expect(screen.getByText(label)).toBeInTheDocument();
  });

  it('loads a valid workflow when a card is chosen, for every example', () => {
    const onSelect = open();
    for (const e of CATALOG) {
      const name = (e.json as { name: string }).name;
      fireEvent.click(cards().find((c) => c.textContent?.includes(name))!);
      const loaded = onSelect.mock.calls.at(-1)![0] as { name: string; nodes: unknown[] };
      expect(loaded.name).toBe(name);
      expect(loaded.nodes).toHaveLength(e.nodeCount);
      const wf = loaded as unknown as { nodes: { id: string; type: string }[]; edges: { source: string; target: string }[] };
      const ids = new Set(wf.nodes.map((n) => n.id));
      expect(wf.nodes.filter((n) => n.type === 'START')).toHaveLength(1);
      expect(wf.nodes.filter((n) => n.type === 'END').length).toBeGreaterThanOrEqual(1);
      expect(ids.size).toBe(wf.nodes.length);                                                     // ids are unique
      expect(wf.edges.every((x) => ids.has(x.source) && ids.has(x.target))).toBe(true);           // no connection to a missing step
    }
  });

  it('finds examples by name, industry or tag', () => {
    open();
    const search = screen.getByPlaceholderText(/Search by name, industry, or tag/);
    fireEvent.change(search, { target: { value: 'failure-handling' } });
    const hits = cards();
    expect(hits.length).toBeGreaterThanOrEqual(5);
    expect(hits.every((c) => !c.textContent?.includes('Supply Chain Monitor'))).toBe(true);     // the teaching example has no such tag
    fireEvent.change(search, { target: { value: 'refund' } });
    expect(cards()).toHaveLength(1);
    expect(cards()[0]).toHaveTextContent('Refund Request Handler');
    fireEvent.change(search, { target: { value: 'try-the-checks' } });
    expect(cards()).toHaveLength(1);
    expect(cards()[0]).toHaveTextContent('Supply Chain Monitor');
  });

  it('says the teaching example is deliberately left with findings', () => {
    open();
    const card = cards().find((c) => c.textContent?.includes('Supply Chain Monitor'))!;
    expect(within(card).getByText(/deliberately/i)).toBeInTheDocument();
  });
});
