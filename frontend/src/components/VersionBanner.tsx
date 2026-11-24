import { useState } from 'react';
import { APP_VERSION } from '../version';
import type { BackendVersion } from '../utils/version';
import { compareVersions } from '../utils/version';

/** A slim notice when the page and the server are on different feature versions (typically a stale cached page after a deploy). */
export function VersionBanner({ backend }: { backend: BackendVersion }) {
  const [dismissed, setDismissed] = useState(false);
  const relation = compareVersions(APP_VERSION, backend.version);
  if (dismissed || (relation !== 'frontend-older' && relation !== 'frontend-newer')) return null;

  return (
    <div className="version-banner" role="status" data-testid="version-banner">
      {relation === 'frontend-older'
        ? <>A newer version of AiFlow is available (this page is {APP_VERSION}, the server is {backend.version}). </>
        : <>This page ({APP_VERSION}) is newer than the server ({backend.version}); some features may not work yet. </>}
      {relation === 'frontend-older' && <button className="btn btn-ghost" onClick={() => window.location.reload()}>Reload</button>}
      <button className="btn btn-ghost" onClick={() => setDismissed(true)} aria-label="Dismiss">✕</button>
    </div>
  );
}
