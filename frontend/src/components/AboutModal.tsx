import { useEffect, useState } from 'react';
import changelog from '../../../CHANGELOG.md?raw';
import { APP_BUILD_DATE, APP_COMMIT, APP_VERSION } from '../version';
import type { BackendVersion } from '../utils/version';
import { compareVersions, versionSummary } from '../utils/version';
import { copyText } from '../utils/download';
import { MarkdownView } from './MarkdownView';

interface Props {
  backend: BackendVersion;
  onClose: () => void;
}

const RELATION_TEXT = {
  match: 'The page and the server are on the same version.',
  'frontend-older': 'The server is newer than this page. Reload the page to get the latest version.',
  'frontend-newer': 'This page is newer than the server. Some features may not work until the server is updated.',
  unknown: '',
} as const;

// Skip the introduction; the dialog shows the releases themselves.
const RELEASES = changelog.includes('## ') ? changelog.slice(changelog.indexOf('## ')) : changelog;

export function AboutModal({ backend, onClose }: Props) {
  const [copied, setCopied] = useState<'yes' | 'no' | null>(null);
  const relation = compareVersions(APP_VERSION, backend.version);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const summary = versionSummary({ version: APP_VERSION, commit: APP_COMMIT, date: APP_BUILD_DATE }, backend);

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal suggest-modal" role="dialog" aria-label="About AiFlow">
        <div className="modal-header">
          <span className="modal-title"><span className="toolbar-logo">⬡</span> AiFlow</span>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="modal-body suggest-body">
          <div className="suite-hint">Design, check, test and share AI workflows.</div>

          <dl className="about-grid" data-testid="about-versions">
            <dt>Version</dt>
            <dd data-testid="about-version">{APP_VERSION}</dd>
            <dt>This page</dt>
            <dd>{APP_COMMIT !== 'unknown' ? `commit ${APP_COMMIT}` : 'commit unknown'}, built {APP_BUILD_DATE}</dd>
            <dt>Server</dt>
            <dd data-testid="about-server">
              {backend.state === 'loading' && 'checking…'}
              {backend.state === 'unreachable' && 'could not be reached'}
              {backend.state === 'ok' && (backend.version
                ? `${backend.version}${backend.commit && backend.commit !== 'unknown' ? ` (commit ${backend.commit})` : ''}`
                : 'version not reported (an older server)')}
            </dd>
          </dl>

          {RELATION_TEXT[relation] && (
            <div className={relation === 'match' ? 'suite-hint' : 'modal-error'} role={relation === 'match' ? 'status' : 'alert'} data-testid="about-relation">
              {RELATION_TEXT[relation]}
            </div>
          )}

          <div>
            <button className="btn btn-ghost" onClick={async () => setCopied((await copyText(summary)) ? 'yes' : 'no')}>
              Copy version info
            </button>
            <span className="suite-hint"> Paste it into a bug report.</span>
            {copied === 'yes' && <span className="suite-hint" role="status"> Copied</span>}
            {copied === 'no' && <span className="assertion-problem" role="status"> Copy was blocked by the browser.</span>}
          </div>

          <div className="suite-coverage-title">What's new</div>
          <div className="about-changelog" data-testid="about-changelog"><MarkdownView source={RELEASES} /></div>
        </div>
      </div>
    </div>
  );
}
