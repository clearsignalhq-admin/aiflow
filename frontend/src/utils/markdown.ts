/**
 * A deliberately small Markdown parser for the documents AiFlow generates (the workflow explanation):
 * headings, paragraphs, bullet and numbered lists (one nested level), pipe tables, rules, images and links.
 * It produces plain data, and the view renders it as React elements, so text is never interpreted
 * as HTML.
 */

export type MdBlock =
  | { type: 'heading'; level: 1 | 2 | 3; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'rule' }
  | { type: 'ul'; items: string[] }
  | { type: 'ol'; items: { text: string; children: string[] }[] }
  | { type: 'table'; header: string[]; rows: string[][] }
  | { type: 'image'; alt: string; src: string };

/** Split a table row on unescaped pipes. */
export function splitRow(line: string): string[] {
  const body = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  const cells: string[] = [];
  let current = '';
  for (let i = 0; i < body.length; i++) {
    if (body[i] === '\\' && body[i + 1] === '|') { current += '|'; i++; continue; }
    if (body[i] === '|') { cells.push(current.trim()); current = ''; continue; }
    current += body[i];
  }
  cells.push(current.trim());
  return cells;
}

const isTableSeparator = (line: string) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(line);

export function parseMarkdown(source: string): MdBlock[] {
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  const blocks: MdBlock[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }

    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length as 1 | 2 | 3, text: heading[2].trim() });
      i++; continue;
    }

    const image = /^!\[([^\]]*)\]\(([^)\s]+)\)\s*$/.exec(line.trim());
    if (image) { blocks.push({ type: 'image', alt: image[1], src: image[2] }); i++; continue; }

    if (/^-{3,}\s*$/.test(line)) { blocks.push({ type: 'rule' }); i++; continue; }

    if (line.trimStart().startsWith('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      const header = splitRow(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trimStart().startsWith('|')) { rows.push(splitRow(lines[i])); i++; }
      blocks.push({ type: 'table', header, rows });
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const items: { text: string; children: string[] }[] = [];
      while (i < lines.length) {
        const item = /^\d+\.\s+(.*)$/.exec(lines[i]);
        if (item) { items.push({ text: item[1], children: [] }); i++; continue; }
        const child = /^\s+[-*]\s+(.*)$/.exec(lines[i]);
        if (child && items.length) { items[items.length - 1].children.push(child[1]); i++; continue; }
        break;
      }
      blocks.push({ type: 'ol', items });
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) { items.push(lines[i].replace(/^[-*]\s+/, '')); i++; }
      blocks.push({ type: 'ul', items });
      continue;
    }

    const para: string[] = [line.trim()];
    i++;
    while (i < lines.length && lines[i].trim() && !/^(#{1,3}\s|-{3,}\s*$|\d+\.\s|[-*]\s|\||!\[)/.test(lines[i])) { para.push(lines[i].trim()); i++; }
    blocks.push({ type: 'paragraph', text: para.join(' ') });
  }
  return blocks;
}

export type Inline =
  | { kind: 'text' | 'bold' | 'italic' | 'code'; text: string }
  | { kind: 'link'; text: string; href: string };

/** The id a heading gets, so `#some-heading` links work (GitHub's rule: lower case, no punctuation, spaces become hyphens). */
export function slugify(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9\s-]/g, '').trim().replace(/\s+/g, '-');
}

/** `**bold**`, `*italic*` / `_italic_`, `code` spans and `[text](link)`; everything else is literal text. */
export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  // `_italic_` only counts at word boundaries, so snake_case identifiers are left alone.
  const pattern = /(\[[^\]]+\]\([^)\s]+\)|\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|(?<![A-Za-z0-9])_[^_\s][^_]*_(?![A-Za-z0-9]))/g;
  let last = 0;
  for (const m of text.matchAll(pattern)) {
    const index = m.index ?? 0;
    if (index > last) out.push({ kind: 'text', text: text.slice(last, index) });
    const token = m[0];
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token);
    if (link) out.push({ kind: 'link', text: link[1], href: link[2] });
    else if (token.startsWith('**')) out.push({ kind: 'bold', text: token.slice(2, -2) });
    else if (token.startsWith('`')) out.push({ kind: 'code', text: token.slice(1, -1) });
    else out.push({ kind: 'italic', text: token.slice(1, -1) });
    last = index + token.length;
  }
  if (last < text.length) out.push({ kind: 'text', text: text.slice(last) });
  return out;
}
