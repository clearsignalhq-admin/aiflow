import { useEffect, useMemo } from 'react';
import { Link, useLocation } from 'react-router-dom';
import guide from '../../../docs/user-guide/README.md?raw';
import { MarkdownView } from '../components/MarkdownView';
import { parseMarkdown, slugify } from '../utils/markdown';
import { APP_VERSION } from '../version';

// The screenshots live next to the guide in the repository; the build gives each a URL.
const IMAGES = import.meta.glob('../../../docs/user-guide/images/*.png', { eager: true, query: '?url', import: 'default' }) as Record<string, string>;
const resolveImage = (src: string) => IMAGES[`../../../docs/user-guide/${src}`] ?? null;

/** The public user guide: the repository's docs/user-guide/README.md, with a contents list. */
export default function GuidePage() {
  const { hash } = useLocation();
  const sections = useMemo(
    () => parseMarkdown(guide).flatMap((b) => (b.type === 'heading' && b.level === 2 ? [{ id: slugify(b.text), text: b.text }] : [])),
    [],
  );

  // Opening /guide#some-section: the content is not there yet when the browser first tries to scroll.
  useEffect(() => {
    if (!hash) return;
    document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView();
  }, [hash]);

  return (
    <div className="guide-page">
      <header className="guide-header">
        <Link to="/" className="shared-brand">⬡ AiFlow</Link>
        <span className="suite-hint">User guide · version {APP_VERSION}</span>
        <span className="guide-header-links">
          <Link to="/app" className="btn btn-primary">Open the app</Link>
        </span>
      </header>
      <div className="guide-body">
        <nav className="guide-toc" aria-label="Contents">
          <div className="guide-toc-title">Contents</div>
          <ul>
            {sections.map((s) => <li key={s.id}><a href={`#${s.id}`}>{s.text}</a></li>)}
          </ul>
        </nav>
        <main className="guide-content" data-testid="guide-content">
          <MarkdownView source={guide} resolveImage={resolveImage} />
        </main>
      </div>
    </div>
  );
}
