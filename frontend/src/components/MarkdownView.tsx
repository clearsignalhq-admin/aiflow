import type { ReactNode } from 'react';
import { parseInline, parseMarkdown } from '../utils/markdown';

function Inline({ text }: { text: string }) {
  return (
    <>
      {parseInline(text).map((part, i): ReactNode => {
        if (part.kind === 'bold') return <strong key={i}>{part.text}</strong>;
        if (part.kind === 'italic') return <em key={i}>{part.text}</em>;
        if (part.kind === 'code') return <code key={i}>{part.text}</code>;
        return <span key={i}>{part.text}</span>;
      })}
    </>
  );
}

/** Renders the small Markdown subset from utils/markdown as React elements (no raw HTML is ever inserted). */
export function MarkdownView({ source }: { source: string }) {
  const blocks = parseMarkdown(source);
  return (
    <div className="md-view">
      {blocks.map((b, i) => {
        switch (b.type) {
          case 'heading': {
            const Tag = (`h${Math.min(b.level + 1, 4)}`) as 'h2' | 'h3' | 'h4';
            return <Tag key={i}><Inline text={b.text} /></Tag>;
          }
          case 'paragraph':
            return <p key={i}><Inline text={b.text} /></p>;
          case 'rule':
            return <hr key={i} />;
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
