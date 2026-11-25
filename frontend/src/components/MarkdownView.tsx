import type { ReactNode } from 'react';
import { parseInline, parseMarkdown, slugify } from '../utils/markdown';

/** Only in-page anchors and web addresses become links; anything else (javascript:, file paths) is shown as plain text. */
function safeHref(href: string): { href: string; external: boolean } | null {
  if (href.startsWith('#') && href.length > 1) return { href, external: false };
  if (/^https?:\/\//i.test(href)) return { href, external: true };
  if (/^\/[A-Za-z0-9/_-]*$/.test(href)) return { href, external: false };   // a path inside this site, such as /app
  return null;
}

function Inline({ text }: { text: string }) {
  return (
    <>
      {parseInline(text).map((part, i): ReactNode => {
        if (part.kind === 'link') {
          const target = safeHref(part.href);
          if (!target) return <span key={i}>{part.text}</span>;
          return <a key={i} href={target.href} {...(target.external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}>{part.text}</a>;
        }
        if (part.kind === 'bold') return <strong key={i}>{part.text}</strong>;
        if (part.kind === 'italic') return <em key={i}>{part.text}</em>;
        if (part.kind === 'code') return <code key={i}>{part.text}</code>;
        return <span key={i}>{part.text}</span>;
      })}
    </>
  );
}

interface Props {
  source: string;
  /** Turns an image path from the Markdown into a URL. Images it cannot resolve show their description instead. */
  resolveImage?: (src: string) => string | null | undefined;
}

/** Renders the small Markdown subset from utils/markdown as React elements (no raw HTML is ever inserted). */
export function MarkdownView({ source, resolveImage }: Props) {
  const blocks = parseMarkdown(source);
  return (
    <div className="md-view">
      {blocks.map((b, i) => {
        switch (b.type) {
          case 'heading': {
            const Tag = (`h${Math.min(b.level + 1, 4)}`) as 'h2' | 'h3' | 'h4';
            return <Tag key={i} id={slugify(b.text)}><Inline text={b.text} /></Tag>;
          }
          case 'paragraph':
            return <p key={i}><Inline text={b.text} /></p>;
          case 'rule':
            return <hr key={i} />;
          case 'image': {
            const url = resolveImage?.(b.src);
            return url
              ? <figure key={i} className="md-figure"><img src={url} alt={b.alt} loading="lazy" /></figure>
              : <p key={i}><em>{b.alt}</em></p>;
          }
          case 'ul':
            return <ul key={i}>{b.items.map((t, j) => <li key={j}><Inline text={t} /></li>)}</ul>;
          case 'ol':
            return (
              <ol key={i}>
                {b.items.map((item, j) => (
                  <li key={j}>
                    <Inline text={item.text} />
                    {item.children.length > 0 && (
                      <ul>{item.children.map((c, k) => <li key={k}><Inline text={c} /></li>)}</ul>
                    )}
                  </li>
                ))}
              </ol>
            );
          case 'table':
            return (
              <table key={i} className="md-table">
                <thead><tr>{b.header.map((h, j) => <th key={j}><Inline text={h} /></th>)}</tr></thead>
                <tbody>
                  {b.rows.map((row, r) => (
                    <tr key={r}>{row.map((cell, c) => <td key={c}><Inline text={cell} /></td>)}</tr>
                  ))}
                </tbody>
              </table>
            );
        }
      })}
    </div>
  );
}
